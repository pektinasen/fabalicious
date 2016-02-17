import inspect, sys
from fabric.colors import green, yellow

from types import TypeType
from base import BaseMethod
from git import GitMethod
from drush import DrushMethod
from ssh import SSHMethod
from composer import ComposerMethod
from scripts import ScriptMethod
from docker import DockerMethod
from slack import SlackMethod
from files import FilesMethod
from drupalconsole import DrupalConsoleMethod
cache = {}

class Factory(object):


  @staticmethod
  def get(name):
    methodClasses = [j for (i,j) in globals().iteritems() if isinstance(j, TypeType) and issubclass(j, BaseMethod)]
    for methodClass in methodClasses:
      if methodClass.supports(name):
        return methodClass(name, sys.modules[__name__])
    #if research was unsuccessful, raise an error
    raise ValueError('No method supporting "%s" found.' % name)


def get(methodName, taskName):
  if methodName in cache:
    m = cache[methodName]
  else:
    m = Factory().get(methodName)
    cache[methodName] = m

  if hasattr(m, taskName) and inspect.ismethod(getattr(m, taskName)):
    return getattr(m, taskName)

  return False


def callImpl(methodName, taskName, configuration, optional, **kwargs):
  # print "calling %s@%s ..." % (methodName, taskName)
  fn = get(methodName, taskName)
  if fn:
    result = fn(configuration, **kwargs)
    return result
  elif not optional:
    raise ValueError('Task "%s" in method "%s" not found!' % (taskName, methodName))


def call(methodName, taskName, configuration, **kwargs):
  preflight('preflight', taskName, configuration, **kwargs)
  result = callImpl(methodName, taskName, configuration, False, **kwargs)
  preflight('postflight', taskName, configuration, **kwargs)
  return result


def preflight(task, taskName, configuration, **kwargs):
  for methodName in configuration['needs']:
    fn = get(methodName, task)
    if fn:
      fn(taskName, configuration, **kwargs)



def runTask(configuration, taskName, **kwargs):
  preflight('preflight', taskName, configuration, **kwargs)
  runTaskImpl(configuration['needs'], taskName + "Prepare", configuration, **kwargs);
  runTaskImpl(configuration['needs'], taskName, configuration, **kwargs);

  if 'nextTasks' in kwargs and len(kwargs['nextTasks']) > 0:
    next_task = kwargs['nextTasks'].pop()
    runTask(configuration, next_task, **kwargs)

  runTaskImpl(configuration['needs'], taskName + "Finished", configuration, **kwargs);
  preflight('postflight', taskName, configuration, **kwargs)


def runTaskImpl(methodNames, taskName, configuration, **kwargs):
  msg_printed = False
  for methodName in methodNames:
    if not msg_printed:
      print yellow('Running task %s on configuration %s' % (taskName, configuration['config_name']))
      msg_printed = True

    callImpl(methodName, taskName, configuration, True, **kwargs)