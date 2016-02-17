from base import BaseMethod
from fabric.api import *
from lib.utils import SSHTunnel, RemoteSSHTunnel
from fabric.colors import green, red
from lib import configuration
import copy

class DrupalConsoleMethod(BaseMethod):

  @staticmethod
  def supports(methodName):
    return methodName == 'drupalconsole'

  def install(self, config):
    with cd(config['tmpFolder']):
      run('curl https://drupalconsole.com/installer -L -o drupal.phar')
      run('mv drupal.phar /usr/local/bin/drupal')
      run('chmod +x /usr/local/bin/drupal')

      print green('Drupal Console installed successfully.')

  def run_drupalconsole(self, config, command):
    with cd(config['siteFolder']):
      run('drupal %s' % command)

  def drupalconsole(self, config, **kwargs):
    if kwargs['command'] == 'install':
        self.install(config)
        return
    with cd(config['siteFolder']):
      self.run_drupalconsole(config, kwargs['command'])
