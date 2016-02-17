#!/usr/bin/env python
# -*- coding: utf-8 -*-

from fabric.api import *
from fabric.state import output, env
from fabric.colors import green, red
import datetime
import yaml
import subprocess, shlex, atexit, time
import os.path
import re
import copy
import glob
import urllib2
import sys
import hashlib
import json
import getpass

settings = 0
verbose_output = False
current_config = 'unknown'

env.forward_agent = True
env.use_shell = False

fabfile_basedir = False



ssh_no_strict_key_host_checking_params = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -q'



class SSHTunnel:
  def __init__(self, bridge_user, bridge_host, dest_host, bridge_port=22, dest_port=22, local_port=2022, strictHostKeyChecking = True, timeout=45):
    self.local_port = local_port

    if not strictHostKeyChecking:
      cmd = 'ssh ' + ssh_no_strict_key_host_checking_params
    else:
      cmd = 'ssh'

    cmd = cmd + ' -vAN -L %d:%s:%d %s@%s' % (local_port, dest_host, dest_port, bridge_user, bridge_host)

    self.p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    start_time = time.time()
    atexit.register(self.p.kill)
    while not 'Entering interactive session' in self.p.stderr.readline():
      if time.time() > start_time + timeout:
        raise Exception("SSH tunnel timed out")
  def entrance(self):
    return 'localhost:%d' % self.local_port



class RemoteSSHTunnel:
  def __init__(self, config, bridge_user, bridge_host, dest_host, bridge_port=22, dest_port=22, local_port=2022, strictHostKeyChecking = True, timeout=45):
    self.local_port = local_port
    self.bridge_host = bridge_host
    self.bridge_user = bridge_user
    if not strictHostKeyChecking:
      remote_cmd = 'ssh ' + ssh_no_strict_key_host_checking_params
      cmd = 'ssh ' + ssh_no_strict_key_host_checking_params
    else:
      remote_cmd = 'ssh'
      cmd = 'ssh'
    remote_cmd = remote_cmd + ' -v -L %d:%s:%d %s@%s -A -N -M ' % (local_port, dest_host, dest_port, bridge_user, bridge_host)
    run_quietly('rm -f ~/.ssh-tunnel-from-fabric')

    ssh_port = 22
    if 'port' in config:
      ssh_port = config['port']

    cmd = cmd + ' -vA -p %d %s@%s' % (ssh_port, config['user'], config['host'])
    cmd = cmd + " '" + remote_cmd + "'"

    print("running remote tunnel")
    print(cmd);

    self.p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    start_time = time.time()

    start_time = time.time()
    atexit.register(self.p.kill)
    while not 'Entering interactive session' in self.p.stderr.readline():
      if time.time() > start_time + timeout:
        raise Exception("SSH tunnel timed out")


  def entrance(self):
    return 'localhost:%d' % self.local_port


def run_quietly(cmd, msg = '', hide_output = None, may_fail=False):
  global verbose_output
  if 'warn_only' in env and env['warn_only']:
    may_fail = True

  if msg != '':
    print msg

  if not hide_output:
    hide_output = ['running', 'output', 'warnings']

  if verbose_output:
    hide_output=[]


  with hide(*hide_output):
    try:
      result = run(cmd)

      if not may_fail and result.return_code != 0:
        print red('%s failed:' %s)
        print result

      return result
    except:
      print red('%s failed' % cmd)

      if output['aborts']:
        raise SystemExit('%s failed' % cmd);





def find_between( s, first, last ):
  try:
    start = s.index( first ) + len( first )
    end = s.index( last, start )
    return s[start:end]
  except ValueError:
    return ""



def get_docker_container_ip(docker_name, docker_host, docker_user, docker_port):

  cmd = 'ssh -p %d %s@%s docker inspect %s | grep IPAddress' % (docker_port, docker_user, docker_host, docker_name)

  try:
    with hide('running', 'output'):
      output = local(cmd, capture=True)
  except SystemExit:
    print red('Docker not running, can\'t get ip')
    return

  ip_address = find_between(output.stdout, '"IPAddress": "', '"')

  return ip_address






def run_custom(config, run_key):

  replacements = {}
  for key in config:
    if type(config[key]) != type({}):
      replacements['%'+key+'%'] = str(config[key])

  pattern = re.compile('|'.join(re.escape(key) for key in replacements.keys()))

  env.output_prefix = False
  if run_key in config:
    with cd(config['rootFolder']), hide('running'):
      for line in config[run_key]:
        line = pattern.sub(lambda x: replacements[x.group()], line)
        result = re.match(r'run_docker_task\((.*)\)', line)
        if result:
          docker_task_name = result.group(1)
          docker(docker_task_name)
        else:
          run(line)

  env.output_prefix = True



def get_settings(key, subkey):
  if key in settings:
    if subkey in settings[key]:
      return settings[key][subkey]

  return False



def header():
  if header.sended not in locals() and header.sended != 1:
    print(green("Fabalicious deployment scripts\n"))
    header.sended = 1
header.sended = 0



def check_source_config(config_name = False):
  check_config()

  if not config_name:
    print(red('copyFrom needs a configuration as a source to copy from'))
    exit(1)

  source_config = get_configuration(config_name)
  if not source_config:
    print(red('can\'t find source config '+config_name))
    exit(1);

  return source_config



def get_version():
  if not env.config['supportsSSH']:
    return 'unknown';

  with cd(env.config['gitRootFolder']):
    with hide('output', 'running'):
      output = run('git describe --always')
      output = output.stdout.splitlines()
      return output[-1].replace('/', '-')



def get_backup_file_name(config, config_name):
  i = datetime.datetime.now()
  return config['backupFolder'] + "/" +get_version()+ '--' + config_name + "--"+i.strftime('%Y-%m-%d--%H-%M-%S')



def run_common_commands():
  env.output_prefix = False

  key = 'development' if env.config['useForDevelopment'] else 'deployment'
  if key in settings['common']:
    for line in settings['common'][key]:
      with hide('running'):
        run(line)

  env.output_prefix = True



def run_drush(cmd, expand_command = True):
  global verbose_output
  env.output_prefix = False
  if expand_command:
    cmd = 'drush ' + cmd
  args = ['running']
  if verbose_output:
    args = []

  with hide(*args):
    run(cmd)
  env.output_prefix = True


def slack(config, type, message):
  if 'slack' not in config:
    return

  slack_config = config['slack']
  if type != 'always' and type not in slack_config['notifyOn']:
    return

  try:
    __import__('imp').find_module('slacker')
    from slacker import Slacker

    slack = Slacker(slack_config['token'])

    # Send a message to #general channel
    username = slack_config['username'] + ' (' + getpass.getuser() + ')'
    version = get_version()
    version_link = None

    attachments = [{
      'fallback': message,
      'color': 'good',
      'fields': [
        {
          'title': 'Configuration',
          'short': True,
          'value': config['config_name'],
        },
        {
          'title': 'Branch / Version',
          'short': True,
          'value': config['branch'] + ' / ' + version,
        },
      ]
    }]

    if 'gitWebUrl' in slack_config:
      version_link = slack_config['gitWebUrl'].replace('%commit%', version)
      attachments[0]['fields'].append({
        'title': 'Git',
        'value': version_link,
      })

    attachments = json.dumps(attachments)

    slack.chat.post_message(slack_config['channel'], message, username=username, attachments=attachments, icon_emoji=slack_config['icon_emoji'])
    print green('Slack-notification sent to %s.' % slack_config['channel'])
  except ImportError:
    print red('Please install slacker on this machine: pip install slacker.')


@task
def notify(message):
  slack(env.config, 'always', message)

@task
def list():
  config = get_all_configurations()
  print("Found configurations for: "+ config['name']+"\n")
  for key, value in config['hosts'].items():
    print '- ' + key



@task
def about(config_name=False):
  if not config_name:
    config_name = current_config
  configuration = get_configuration(config_name)
  if configuration:
    print("Configuration for " + config_name)
    for key, value in configuration.items():
      if isinstance(value, dict):
        print(key)
        for dict_key, dict_value in value.items():
          print('  ' + dict_key.ljust(23) + ': '+ str(dict_value))
      elif hasattr(value, "__len__") and not hasattr(value, 'strip'):
          print key
          for list_value in value:
            print(' '.ljust(25) + ': '+ str(list_value))
      else:
        print(key.ljust(25) + ': '+ str(value))



@task
def config(config_name='local'):
  config = get_configuration(config_name)
  apply_config(config, config_name)


@task
def getProperty(in_key):
  with hide('output', 'running', 'warnings'):
    check_config()
    keys = in_key.split('/')
    c = env.config
    for key in keys:
      if key in c:
        c = c[key]
      else:
        print red('property %s not found!' % in_key)
        exit(1)

  print c
  exit(0)


@task
def reset(withPasswordReset=False):
  check_config()
  print green('Resetting '+ settings['name'] + "@" + current_config)

  run_custom(env.config, 'resetPrepare')

  if env.config['hasDrush'] == True:
    with cd(env.config['siteFolder']):
      if env.config['useForDevelopment'] == True:
        if withPasswordReset in [True, 'True', '1']:
          run_drush('user-password admin --password="admin"')
        with warn_only():
          run_quietly('chmod -R 777 ' + env.config['filesFolder'])
      with warn_only():
        if 'deploymentModule' in settings:
          run_drush('en -y ' + settings['deploymentModule'])
      run_drush('updb -y')
      with warn_only():
        run_drush('fra -y')

        run_common_commands()
        run_drush(' cc all')

  run_custom(env.config, 'reset')
  slack(env.config, 'reset', 'Reset finished.')



def backup_sql(backup_file_name, config):
  if(config['hasDrush']):
    with cd(config['siteFolder']):
      with warn_only():
        dump_options = ''
        if 'sqlSkipTables' in settings and settings['sqlSkipTables'] != False:
          dump_options = '--structure-tables-list=' + ','.join(settings['sqlSkipTables'])

        run_quietly('mkdir -p ' + config['backupFolder'])
        run_quietly('rm -f '+backup_file_name)
        if config['supportsZippedBackups']:
          run_quietly('rm -f '+backup_file_name+'.gz')
          dump_options += ' --gzip'

      run_drush('sql-dump ' + dump_options + ' --result-file=' + backup_file_name)



@task
def backup(withFiles=True):
  check_config()
  if not env.config['supportsBackups']:
    return

  print green('backing up files and database of ' + settings['name'] + "@" + current_config)


  exclude_files_setting = get_settings('excludeFiles', 'backup')
  exclude_files_str = ''
  if exclude_files_setting:
    exclude_files_str = ' --exclude="' + '" --exclude="'.join(exclude_files_setting) + '"'

  backup_file_name = get_backup_file_name(env.config, current_config)
  backup_sql(backup_file_name+'.sql', env.config)

  if withFiles and withFiles != '0':
    with cd(env.config['filesFolder']):
      run_quietly('tar '+exclude_files_str+' -czPf ' + backup_file_name + '.tgz *', 'Backing up files')
    if 'privateFilesFolder' in env.config:
      with cd(env.config['privateFilesFolder']):
        run_quietly('tar '+exclude_files_str+' -czPf ' + backup_file_name + '_private.tgz *', 'Backup up private files')
  else:
    print "Backup of files skipped per request..."

  run_custom(env.config, 'backup')

  slack(env.config, 'backup', 'Backup finished to ' + backup_file_name)



@task
def backupDB():
  backup(False)
def clean_working_copy():

  with hide('running', 'output', 'warnings'), warn_only():
    result = run('git diff --exit-code --quiet')
    return result.return_code == 0


@task
def deploy(resetAfterwards=True):

  check_config()
  branch = env.config['branch']

  if not env.config['useForDevelopment'] and env.config['supportsBackups']:
    backup_file_name = get_backup_file_name(env.config, current_config)
    print green('backing up DB of ' + settings['name'] + '@' + current_config+ ' to '+backup_file_name+'.sql')
    backup_sql(backup_file_name+'.sql', env.config)

  print green('Deploying branch '+ branch + " to " + settings['name'] + "@" + current_config)

  run_custom(env.config, 'deployPrepare')

  if env.config['supportsSSH']:
    with cd(env.config['gitRootFolder']):

      if not clean_working_copy():
        print red("Working copy is not clean, aborting.\n")
        run('git status')
        exit(1)
      # run not quietly to see ssh-warnings, -confirms
      run('git fetch -q origin')
      run('git checkout '+branch)
      run('git fetch --tags')

      git_options = ''
      if 'pull' in env.config['gitOptions']:
        git_options = ' '.join(env.config['gitOptions']['pull'])

      run('git pull -q '+ git_options + ' origin ' +branch)

      if not env.config['ignoreSubmodules']:
        run('git submodule init')
        run('git submodule sync')
        run('git submodule update --init --recursive')
      if env.config['needsComposer']:
        run('composer install')

  run_custom(env.config, 'deploy')

  if resetAfterwards and resetAfterwards != '0':
    reset()

  run_custom(env.config, 'deployFinished')

  slack(env.config, 'deploy', 'Deployment finished sucessfully')


@task
def version():
  print green(settings['name'] + ' @ ' + current_config+' tagged with: ' + get_version())



def rsync(config_name, files_type = 'filesFolder'):

  source_config = check_source_config(config_name)

  if not env.config['supportsCopyFrom']:
    print red("The configuration '"+ current_config + "' does not support copyFrom")
    return

  print green('Copying files from '+ config_name + " to " + current_config)

  source_ssh_port = '22'
  if 'port' in source_config:
    source_ssh_port = source_config['port']

  with cd(env.config['rootFolder']):
    exclude_files_setting = get_settings('excludeFiles', 'copyFrom')
    exclude_files_str = ''
    if exclude_files_setting:
      exclude_files_str = ' --exclude "' + '" --exclude "'.join(exclude_files_setting) + '"'


    rsync = 'rsync -rav --no-o --no-g ';
    rsync += ' -e "ssh -T -o Compression=no '+ssh_no_strict_key_host_checking_params+' -p '+str(source_ssh_port)+'"'
    rsync += ' ' + exclude_files_str
    rsync += ' ' + source_config['user']+'@'+source_config['host']
    rsync += ':' + source_config[files_type]+'/*'
    rsync += ' '
    rsync += env.config[files_type]

    with warn_only():
      run(rsync)



def _copyFilesFrom(config_name = False):
  rsync(config_name)
  source_config = check_source_config(config_name)
  if 'privateFilesFolder' in env.config and 'privateFilesFolder' in source_config:
    rsync(source_config, 'privateFilesFolder')



def _copyDBFrom(config_name = False):
  source_config = check_source_config(config_name)
  target_config = check_source_config(current_config)

  if not env.config['supportsCopyFrom']:
    print red("The configuration '"+ current_config + "' does not support copyFrom")
    return

  print green('Copying database from '+ config_name + " to " + current_config)

  if(env.config['hasDrush']):

    source_ssh_port = '22'
    if 'port' in source_config:
      source_ssh_port = source_config['port']

    ssh_args = ' ' + source_config['user']+'@'+source_config['host']

    no_strict_host_key_checking = False
    if settings['usePty'] == False:
      no_strict_host_key_checking = True

    if 'sshTunnel' in source_config:
      if ('strictHostKeyChecking' in source_config['sshTunnel']) and (source_config['sshTunnel']['strictHostKeyChecking'] == False):
        no_strict_host_key_checking = True

    if no_strict_host_key_checking:
      ssh_args = " " + ssh_no_strict_key_host_checking_params + ssh_args

    sql_name_source = source_config['tmpFolder'] + config_name + '.sql'
    sql_name_target = target_config['tmpFolder'] + config_name + '_target.sql'

    # drush has no predictable behaviour
    if source_config['supportsZippedBackups']:
      sql_name_target += '.gz'

    # create sql-dump on source
    execute(backup_sql, sql_name_source, source_config, host=source_config['user']+'@'+source_config['host']+':'+str(source_ssh_port))

    if source_config['supportsZippedBackups']:
      sql_name_source += '.gz'


    # copy sql to target
    run('scp -P '+str(source_ssh_port)+' '+ssh_args+':'+sql_name_source+' '+sql_name_target+ ' >>/dev/null')

    # cleanup and remove file from source
    run('ssh -p '+str(source_ssh_port)+' '+ssh_args+' rm ' + sql_name_source)

    # import sql into target
    with cd(env.config['siteFolder']):
      if source_config['supportsZippedBackups']:
        run_drush('zcat '+ sql_name_target + ' | $(drush sql-connect)', False)
      else:
        run_drush('drush sql-cli < ' + sql_name_target, False)

      run_quietly('rm '+sql_name_target)



@task
def copyFrom(config_name = False, copyFiles = True, copyDB = True):
  source_config = check_source_config(config_name)
  remote_tunnel = False
  if 'sshTunnel' in source_config:
    remote_tunnel = create_ssh_tunnel(env.config, source_config['sshTunnel'], True)
    tunnel = create_ssh_tunnel(env.config, source_config['sshTunnel'], False)


  if copyDB:
    _copyDBFrom(config_name)
  if copyFiles:
    _copyFilesFrom(config_name)
  if copyDB:
    reset(withPasswordReset=True)



@task
def copyFilesFrom(config_name = False):
  copyFrom(config_name, True, False)



@task
def copyDBFrom(config_name = False):
  copyFrom(config_name, False, True)



@task
def drush(drush_command):
  check_config()
  if (env.config['hasDrush']):
    with cd(env.config['siteFolder']):
      run_drush(drush_command)



@task
def install(distribution='minimal', ask='True', version=7):
  check_config()
  if env.config['useForDevelopment'] and env.config['supportsInstalls']:
    if 'database' not in env.config:
      print red('missing database-dictionary in config '+current_config)
      exit(1)

    validate_dict(['user', 'pass', 'name', 'host'], env.config['database'], 'Missing database configuration: ')

    print green('Installing fresh database for '+ current_config)

    o = env.config['database']
    run_quietly('mkdir -p '+env.config['siteFolder'])
    with cd(env.config['siteFolder']):
      mysql_cmd  = 'CREATE DATABASE IF NOT EXISTS '+o['name']+'; '
      mysql_cmd += 'GRANT ALL PRIVILEGES ON '+o['name']+'.* TO '+o['user']+'@localhost IDENTIFIED BY \''+o['pass']+'\'; FLUSH PRIVILEGES;'

      run_quietly('mysql -h ' + o['host'] + ' -u '+o['user']+' --password='+o['pass']+' -e "'+mysql_cmd+'"', 'Creating database')
      if env.config['hasDrush']:
        with warn_only():
          run_quietly('chmod u+w '+env.config['siteFolder'])
          run_quietly('chmod u+w '+env.config['siteFolder']+'/settings.php')
          run_quietly('rm -f '+env.config['siteFolder']+'/settings.php.old')
          run_quietly('mv '+env.config['siteFolder']+'/settings.php '+env.config['siteFolder']+'/settings.php.old 2>/dev/null')

        sites_folder = os.path.basename(env.config['siteFolder'])
        options = ''
        if ask.lower() == 'false' or ask.lower() == '0':
          options = ' -y'
        options += ' --sites-subdir='+sites_folder
        options += ' --account-name=admin'
        options += ' --account-pass=admin'
        options += '  --db-url=mysql://' + o['user'] + ':' + o['pass'] + '@' + o['host'] + '/' +o ['name']
        run_drush('site-install ' + distribution + ' ' + options)

        with warn_only():
          if version <= 7:
            run_drush('en features -y')
            if 'deploymentModule' in settings:
              run_drush('en -y '+settings['deploymentModule'])

      reset()
  else:
    print red('Aborting; missing hasDrush, useForDevelopment or supportsInstalls in  '+current_config)



@task
def copySSHKeyToDocker():
  check_config()
  if not 'dockerKeyFile' in settings:
    print(red('missing dockerKeyFile in fabfile.yaml'))
    return

  key_file = settings['dockerKeyFile']
  with cd(env.config['rootFolder']), hide('commands', 'output'), lcd(fabfile_basedir):
    run('mkdir -p /root/.ssh')
    if 'dockerKeyFile' in settings:
      put(key_file, '/root/.ssh/id_rsa')
      put(key_file+'.pub', '/root/.ssh/id_rsa.pub')
      run('chmod 600 /root/.ssh/id_rsa')
      run('chmod 644 /root/.ssh/id_rsa.pub')
      put(key_file+'.pub', '/tmp')
      run('cat /tmp/'+os.path.basename(key_file)+'.pub >> /root/.ssh/authorized_keys')
      run('rm /tmp/'+os.path.basename(key_file)+'.pub')
      print green('Copied keyfile to docker.')

    if 'dockerAuthorizedKeyFile' in settings:
      authorized_keys_file = settings['dockerAuthorizedKeyFile']
      put(authorized_keys_file, '/root/.ssh/authorized_keys')
      print green('Copied authorized keys to docker.')
    run('chmod 700 /root/.ssh')



@task
def behat(preset=False, options='', name=False, format=False, out=False):
  check_config()

  # use default preset if available
  if not preset and 'default' in env.config['behat']['presets']:
    preset = 'default'

  # use given preset and append it to existing options
  if preset:
    if not preset in env.config['behat']['presets']:
      print red('Preset %s is missing from "behat/presets"-configuration' % preset)
      exit(1)

    options += env.config['behat']['presets'][preset]

  if name:
    options += ' --name="' + name + '"'
  if out:
    options += ' --out="' + out + '"'
  if format:
    options += ' --format="' + format + '"'



  if not 'run' in env.config['behat']:
    print(red('missing "run" in "behat"-section in fabfile.yaml'))
    exit(1)
  env.output_prefix = False
  with cd(env.config['gitRootFolder']):
    run(env.config['behat']['run'] + ' ' + options)
  env.output_prefix = True



@task
def installBehat():
  check_config()

  if not 'install' in env.config['behat']:
    print(red('missing "install" in "behat"-section in fabfile.yaml'))
    exit(1)

  env.output_prefix = False
  with cd(env.config['gitRootFolder']):
    for line in env.config['behat']['install']:
      run(line)
  env.output_prefix = True



def expand_subtasks(tasks, task_name):
  commands = []

  for line in tasks[task_name]:
    result = re.match(r'run_task\((.*)\)', line)
    if result:
      sub_task_name = result.group(1)
      if sub_task_name in tasks:
        for cmd in expand_subtasks(tasks, sub_task_name):
          commands.append(cmd)
      else:
        print red("subtask not found in tasks: "+sub_task_name)
        exit(1)
    else:
      commands.append(line)

  return commands


def docker_callback_fail_on_error(state, flag):
  if flag == '1':
    state['warnOnly'] = False
  else:
    state['warnOnly'] = True


def docker_callback_echo(state, str, color = False):
  if color == 'red':
    print red(str)
  elif color == 'green':
    print green(str)
  else:
    print str


def docker_callback_execute_host_task(state, task, *args):
  check_config();

  hostStr = env.config['user'] + '@' + env.config['host'] + ":" + str(env.config['port'])

  if len(args) > 0:
    execute(task, args, host=hostStr)
  else:
    execute(task, host=hostStr)


@task
def waitForServices():
  check_config()
  max_tries = 20
  try_n = 0

  while(True):
    try_n += 1
    try:
      with cd(env.config['rootFolder']), hide('commands'):

        output = run('supervisorctl status')
        output = output.stdout.splitlines()
        count_running = 0
        count_services = 0;
        for line in output:
          if line.strip() != '':
            count_services += 1
            if line.find('RUNNING'):
              count_running += 1
        if count_services == count_running:
          print green('Services up and running!')
          break;

    except:
      # TODO:
      # handle only relevant exceptions like
      # fabric.exceptions.NetworkError

      if (try_n < max_tries):
        # Let's wait and try again...
        print "Wait for 5 secs and try again."
        time.sleep(5)
      else:
        print red("Supervisord not coming up at all")
        break


@task
def docker(subtask=False, **kwargs):
  if not subtask:
    print red('Missing subtask for task docker.')
    exit(1)

  check_config()
  if not 'docker' in env.config:
    print red('no docker configuration found.')
    exit(1)

  # validate host-configuration
  keys = ("name", "configuration")
  validate_dict(keys, env.config['docker'], 'Docker-configuraton '+current_config+' has missing key')


  if not 'dockerHosts' in settings:
    print(red('No dockerHosts-configuration found'))
    exit(1)

  all_docker_hosts = settings['dockerHosts']
  config_name = env.config['docker']['configuration']
  docker_configuration = get_docker_configuration(config_name, env.config)
  if not docker_configuration:
    print(red('Could not find docker-configuration %s in dockerHosts' % (config_name)))
    print('Available configurations: ' +  ', '.join(all_docker_hosts.keys()))

    exit(1)

  keys = ("host", "port", "user", "tasks", "rootFolder")
  validate_dict(keys, docker_configuration, 'dockerHosts-Configuraton '+config_name+' has missing key')

  if subtask == "startRemoteAccess":
    ip = get_docker_container_ip(env.config['docker']['name'], docker_configuration['host'], docker_configuration['user'], docker_configuration['port'])

    if not ip:
      print red('Could not get docker-ip-address.')
      exit(1)

    public_ip = '0.0.0.0'
    if 'public_ip' in kwargs:
      public_ip = kwargs['public_ip']
    print green("I am about to start the port forwarding via SSH. If you are finished, just type exit after the prompt.")
    local("ssh -L%s:8888:%s:80 -p %s %s@%s" % (public_ip, ip, docker_configuration['port'], docker_configuration['user'], docker_configuration['host']))
    exit(0)

  if subtask not in docker_configuration['tasks']:
    print(red('Could not find subtask %s in dockerHosts-configuration %s' % (subtask, config_name)))
    print('Available subtasks: ' +  ', '.join(docker_configuration['tasks'].keys()))
    exit(1)

  print(green("Running task '{subtask}' on guest-host '{docker_host}' for container '{container}'".format(subtask=subtask, docker_host=docker_configuration['host'], container=env.config['docker']['name']) ))

  commands = expand_subtasks(docker_configuration['tasks'], subtask)

  parsed_commands = []

  replacements = {}
  for key in ('user', 'host', 'port', 'branch', 'rootFolder', 'gitRootFolder'):
    if key in env.config:
      replacements['%guest.'+key+'%'] = str(env.config[key])
  for key in ('user', 'host', 'port', 'rootFolder'):
    replacements['%'+key+'%'] = str(docker_configuration[key])

  for key in env.config['docker']:
    replacements['%'+key+'%'] = str(env.config['docker'][key])

  for key in kwargs:
    replacements['%'+key+'%'] = str(kwargs[key])

  pattern = re.compile('|'.join(re.escape(key) for key in replacements.keys()))

  for line in commands:
    result = pattern.sub(lambda x: replacements[x.group()], line)
    parsed_commands.append(result)

  host_str = docker_configuration['user'] + '@'+docker_configuration['host']+':'+str(docker_configuration['port'])

  if 'password' in docker_configuration:
    env.passwords[host_str]= docker_configuration['password']

  callbacks = {
    'fail_on_error':  docker_callback_fail_on_error,
    'echo': docker_callback_echo,
    'execute': docker_callback_execute_host_task
  }

  execute(run_script, docker_configuration['rootFolder'], parsed_commands, callbacks, host=host_str)



@task
def run_script(rootFolder=False, commands=False, callbacks=False):
  if not rootFolder:
    return;

  pattern = re.compile('\%(\S*)\%')


  state = { 'warnOnly': True }
  # preflight
  ok = True
  for line in commands:
    if pattern.search(line) != None:
      print red('Found replacement-pattern in script-line %s, aborting ...' % line)
      ok = False

  if not ok:
    return

  for line in commands:
    with cd(rootFolder):
      handled = False
      if callbacks:
        start_p = line.find('(')
        end_p = line.rfind(')')

        if start_p >= 0 and end_p > 0:
          func_name = line[0:start_p]

          if func_name in callbacks:
            arguments = False
            func_args = line[start_p+1: end_p]
            if func_args.strip() != '':
              arguments = func_args.split(',')
              arguments = map(lambda x: x.strip(), arguments)

            if arguments:
              callbacks[func_name](state, *arguments)
            else:
              callbacks[func_name](state)
            handled = True

      if not handled:
        with hide('running'):
          if state['warnOnly']:
            with warn_only():
              run(line)
          else:
            run(line)



def get_backups_list():
  result = []
  if not env.config['supportsSSH']:
    return result;

  with cd(env.config['backupFolder']), hide('running', 'output', 'warnings'), warn_only():
    for ext in ('*.gz', '*.tgz', '*.sql'):
      output = run('ls -l ' + ext + ' 2>/dev/null')
      lines = output.stdout.splitlines()
      for line in lines:
        tokens = line.split()

        if(len(tokens) >= 9):
          line = tokens[8]
          filename, file_ext = os.path.splitext(line)
          if(file_ext == '.gz'):
            filename, file_ext = os.path.splitext(filename)
          tokens = filename.split('--')
          if file_ext == '.sql':
            type = 'sql'
          else:
            type = 'files'
          if(len(tokens) >= 4) and (tokens[1] == current_config):
            result.append({ 'commit': tokens[0], 'date': tokens[2], 'time': tokens[3], 'file': line, 'type': type})

  result = sorted(result, key=lambda k: k['file'], reverse=True)

  return result



@task
def listBackups():
  check_config()
  results = get_backups_list()

  print "\nFound backups for "+ current_config + ":"
  for result in results:

    print "{date} {time}  |  {commit:<30}  |  {file}".format(**result)



def get_backup_files_for_commit(commit):
  results = get_backups_list()
  files = { 'sql': False, 'files': False, 'commit': False }
  found = False

  for result in results:
    if result['commit'] == commit:
      files[result['type']] = result['file']
      files['commit'] = result['commit']
      found = True

  if not found:
    print 'Could not find requested commit, trying by file-name ...'
    for result in results:
      if result['file'].find(commit) >= 0:
        files[result['type']] = result['file']
        files['commit'] = result['commit']
        found = True

  if not found:
    print red('Could not find requested backup ' + commit+'!')
    list_backups();
    exit(1)

  return files

@task
def getBackup(commit):
  check_config()
  files = get_backup_files_for_commit(commit)

  to_copy = []
  if 'sql' in files:
    to_copy.append(files['sql'])

  if 'files' in files and files['files']:
    to_copy.append(files['files'])

  for file in to_copy:
    remotePath = env.config['backupFolder'] + "/" + file
    localPath = './' + file

    get(remote_path=remotePath, local_path=localPath)

@task
def restore(commit, drop=0):
  check_config()
  files = get_backup_files_for_commit(commit)

  # restore sql
  if files['sql']:
    with cd(env.config['siteFolder']):

      if drop:
        run_drush('sql-drop')

      sql_name_target = env.config['backupFolder'] + '/' + files['sql']
      if env.config['supportsZippedBackups']:
        run_drush('zcat '+ sql_name_target + ' | $(drush sql-connect)', False)
      else:
        run_drush('drush sql-cli < ' + sql_name_target, False)

      print(green('SQL restored from ' + files['sql']))


  # restore files
  if files['files']:
    # move current files folder to backup
    ts = datetime.datetime.now().strftime('%Y%m%d.%H%M%S')
    old_files_folder = env.config['filesFolder'] + '.' + ts + '.old'
    with warn_only():
      run_quietly('chmod -R u+x '+env.config['filesFolder'])
      run_quietly('rm -rf '+ old_files_folder)
      run_quietly('mv ' + env.config['filesFolder'] + ' '+old_files_folder)

    tar_file = env.config['backupFolder'] + '/' + files['files']
    run_quietly('mkdir -p ' + env.config['filesFolder'])
    with cd(env.config['filesFolder']):
      run_quietly('tar -xzvf ' + tar_file, 'Unpacking files')

    print(green('files restored from ' + files['files']))

  # restore git
  with cd(env.config['gitRootFolder']):

    run('git checkout ' + files['commit'])

    print(green('source restored to ' + files['commit']))

  reset()



@task
def updateDrupalCore(version=7, branch="feature/drupal-update"):
  check_config()
  if not env.config['useForDevelopment']:
    print red('drupalUpdateCore not supported for staging/live environments ...')
    exit(1)

  backupDB()

  # create new branch
  with cd(env.config['gitRootFolder']):
    run_quietly('git checkout -b "%s"' % branch)

  # download drupal
  with cd(env.config['rootFolder']):
    run_quietly('rm -rf /tmp/drupal-update')
    run_quietly('mkdir -p /tmp/drupal-update')
    run_drush('dl --destination="/tmp/drupal-update" --default-major="%d" drupal ' % version)

  # copy files to root-folder
  with(cd('/tmp/drupal-update')), hide('running'):
    drupal_folder = run('ls').stdout.strip()
    # print drupal_folder

    run('rsync -rav --no-o --no-g %s/* %s' % (drupal_folder, env.config['rootFolder']) )

  # rename branch, if not customized
  if branch == 'feature/drupal-update':
    new_branch = 'feature/drupal-update-' + drupal_folder.replace('drupal-', '')
    with cd(env.config['rootFolder']):
      run_quietly('git branch -m "%s" "%s" ' % (branch, new_branch))

    branch = new_branch

  # remove temporary files
  with cd(env.config['rootFolder']):
    run_quietly('rm -rf /tmp/drupal-update')

  print green("Updated drupal successfully to '%s'. Please review the changes in the new branch %s." % (drupal_folder, branch))



@task
def restoreSQLFromFile(full_file_name):
  check_config()
  sql_name_target = env.config['tmpFolder'] + 'manual_upload.sql'

  fileName, fileExtension = os.path.splitext(full_file_name)
  zipped = fileExtension == '.gz'
  if zipped:
    sql_name_target += '.gz'

  put(full_file_name, sql_name_target)

  # import sql into target
  with cd(env.config['siteFolder']):
    if zipped:
      run_drush('zcat '+ sql_name_target + ' | $(drush sql-connect)', False)
    else:
      run_drush('drush sql-cli < ' + sql_name_target, False)

    run_quietly('rm '+sql_name_target)



@task
def ssh():
  check_config()
  with cd(env.config['rootFolder']):
    open_shell()

@task
def putFile(fileName):
  check_config()
  put(fileName, env.config['tmpFolder'])

@task
def getFile(remotePath, localPath='./'):
  check_config()
  get(remote_path=remotePath, local_path=localPath)

@task
def verbose():
  global verbose_output
  verbose_output = True

@task
def getSQLDump():
  check_config()

  file_name = env.config['config_name'] + "--" + time.strftime("%Y%m%d-%H%M%S") + '.sql'

  print green('Get SQL dump from %s' % env.config['config_name'])

  file_name = '/tmp/' + file_name
  backup_sql(file_name, env.config)
  if env.config['supportsZippedBackups']:
    file_name += '.gz'
  getFile(file_name)
  run('rm ' + file_name);

