import datetime
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import redis

import config


def signal_handler(signal, frame):
    print('Shutting down worker')
    r.decr('workers')
    sys.exit(0)


def setup_worker():
    #register as a worker
    workers = r.get('workers')
    if workers is None:
        r.set('workers', 0)
    else:
        print "found {0} workers".format(workers)
        if int(workers) >= config.workers:
            # we already have enough workers
            print "deactivating because we already have enough workers"
            sys.exit()
    r.incr('workers')


def write_log(work_item, response):
    path = config.logpath
    org, project, pr = work_item.split('/')
    unix_seconds = datetime.datetime.utcnow().strftime('%s')
    filename =  "{0}+{1}+{2}+{3}".format(org,project,pr,unix_seconds)
    with open(path + "/" + filename, 'w') as f:
        f.write("Test log\n")
        f.write("Test performed at {0} - {1}\n".format(unix_seconds, datetime.datetime.utcnow()))
        f.write("{0}/{1} PR # {2}\n".format(org, project, pr))
        if response['success'] == 0:
            f.write("Tests passed\n")
        else:
            f.write("Tests failed\n")
        for line in response['gemout']:
            f.write(line)
        for line in response['gemerr']:
            f.write(line)
        for line in response['out']:
            f.write(line)
        for line in response['err']:
            f.write(line)
    f.closed
    return (filename)


def main_loop():
    #never exits
    while True:
        print 'looping'
        work_item = r.lpop('todo')
        if work_item == None:
            time.sleep(5)
            continue
        tempdir = create_pr_env(work_item)
        response = run_beaker_rspec(tempdir)
        if response['success'] == 0:
            print "Tests passed"
        else:
            print "Tests failed"
        log_path = write_log(work_item, response)
        print "log written to {0}".format(log_path)
        r.rpush('completed', log_path)
        clean_tempdir(tempdir)


def create_pr_env(work_item):
    print "working on {0}".format(work_item)
    org, project, pr = work_item.split('/')
    tempdir = tempfile.mkdtemp()
    git_clone = subprocess.call(["git", "clone", "https://github.com/{0}/{1}".format(org, project), tempdir + "/job"])
    subprocess.Popen(["git", "fetch", "origin", "pull/{0}/head:pr_{0}".format(pr)], cwd=(tempdir + "/job")).communicate()
    subprocess.Popen(["git", "checkout", "pr_{0}".format(pr)], cwd=(tempdir + "/job")).communicate()
    return str(tempdir)


def run_beaker_rspec(tempdir):
    jobdir = tempdir + "/job"
    print "running in {0}".format(jobdir)
    os.mkdir(jobdir + '/.bundled_gems')
    runenv = os.environ.copy()
    runenv["GEM_HOME"]=(jobdir + '/.bundled_gems')
    gem = subprocess.Popen(["bundle", "install"], cwd=jobdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=runenv)
    gemout, gemerr = gem.communicate()
    beaker = subprocess.Popen(["bundle", "exec", "rspec", "spec/acceptance"], cwd=jobdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=runenv)
    out, err = beaker.communicate()
    response = { 'gemout'  : gemout,
                 'gemerr'  : gemerr,
                 'out'     : out,
                 'err'     : err,
                 'success' : beaker.returncode
                 }
    return response


def clean_tempdir(tempdir):
    shutil.rmtree(tempdir)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    r = redis.StrictRedis(host='localhost', port=6379, db=0)
    setup_worker()
    main_loop()


