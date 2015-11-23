#!/usr/bin/env python

"""
This script will configure an xGDS site installation using puppet.  You
can specify whether you want a development or production setup.
"""


def dosys(cmd, exitOnError=True):
    logging.info('executing: %s', cmd)
    ret = os.system(cmd)
    if ret != 0:
        logging.warning('dosys: command "%s" exited with non-zero return value %s', cmd, ret)
        if exitOnError:
            logging.error('dosys: exitOnError is True, exiting')
            sys.exit(1)
    return ret


def isPackageInstalled(pkg):
    ret = dosys('dpkg -s %s | grep installed' % pkg, exitOnError=False)
    return (ret == 0)


def getPuppetVersion():
    try:
        versionText = subprocess.check_output(['puppet', '--version']).strip()
        versionTuple = tuple([int(n) for n in versionText.split('.')])
        return versionTuple
    except OSError:
        return None


def installPuppet():
    puppetInstalled = isPackageInstalled('puppet')
    if puppetInstalled:
        puppetVersion = getPuppetVersion()
    if puppetInstalled and puppetVersion >= (3, 8, 1):
        logging.info('recent puppet is already installed')
    else:
        tmpDir = tempfile.mkdtemp('puppet')
        dosys('curl -o %s/puppetlabs-release-trusty.deb https://apt.puppetlabs.com/puppetlabs-release-trusty.deb' % tmpDir)
        dosys('sudo dpkg -i %s/puppetlabs-release-trusty.deb' % tmpDir)
        dosys('sudo apt-get update')
        if puppetInstalled:
            dosys('sudo apt-get upgrade -y puppet')
        else:
            dosys('sudo apt-get install -y puppet')

    # suppress spurious warning about missing hiera.yaml file
    hieraPath = '/etc/puppet/hiera.yaml'
    if not os.path.exists(hieraPath):
        dosys('sudo touch %s' % hieraPath)

    # suppress spurious warning about deprecated templatedir setting
    puppetConfPath = '/etc/puppet/puppet.conf'
    puppetConfOrig = puppetConfPath + '.orig'
    ret = dosys('grep templatedir %s' % puppetConfPath, exitOnError=False)
    if ret == 0:
        # puppet.conf file has templatedir line; remove it
        if os.path.exists(puppetConfOrig):
            logging.info('%s exists, not changing it' % puppetConfOrig)
        else:
            dosys('sudo cp %s %s' % (puppetConfPath, puppetConfOrig))
        dosys('sudo sh -c "grep -v templatedir %s > %s"' % (puppetConfOrig, puppetConfPath))


def symlinkDeployRepo(repo, PUPPET_DIR):
    # if the /vagrant dir exists, we are in a vagrant guest, and
    # /vagrant should point to a checkout of <site>_deploy on the
    # host file system. to avoid confusion, let's symlink to that single
    # copy of the deploy repo, which we can edit from either host or
    # guest, rather than checking out a second copy that can get out of
    # sync.
    thisDir = os.path.dirname(__file__)
    repoDir = PUPPET_DIR + repo
    if os.path.exists(repoDir):
        logging.info('%s exists, not changing existing config', repoDir)
    else:
        if not os.path.exists(PUPPET_DIR):
            dosys('mkdir -p %s' % PUPPET_DIR)
        dosys('ln -s %s %s' % (thisDir, repoDir))


def linkExistingSource(repo, GDS_DIR, VAGRANT_DIR):
    """ If the user checked out the source code on the host machine, it will be in /vagrant.
    Link it to GDS_DIR
    """
    fullPath = os.path.join(VAGRANT_DIR, repo)
    if os.path.exists(fullPath):
        if not os.path.exists(GDS_DIR):
            dosys('mkdir -p %s' % GDS_DIR)
        dosys('ln -s %s %s' % (fullPath, GDS_DIR))
        return True
    return False


def checkoutSourceRepo(repo, GIT_URL_PREFIX, GDS_DIR, inVagrant=True):
    import os
    if inVagrant:
        dosys('sudo apt-get install -y git-core')
        repoDir = GDS_DIR + repo
        if not os.path.exists(GDS_DIR):
            dosys('mkdir -p %s' % GDS_DIR)
    else:
        GDS_DIR = '.'
        repoDir = repo
        print "Set GDS_DIR to %s" % GDS_DIR 
    if os.path.exists(repoDir):
        logging.info('%s exists, not changing existing config', repoDir)
    else:
        print 'cd %s && git clone --recursive %s/%s' % (GDS_DIR, GIT_URL_PREFIX, repo)
        print 'cd %s/%s && git submodule foreach git checkout master' % (GDS_DIR, repo)
        dosys('cd %s && git clone --recursive %s/%s' % (GDS_DIR, GIT_URL_PREFIX, repo))
        dosys('cd %s/%s && git submodule foreach git checkout master' % (GDS_DIR, repo))


def setupPuppetFacts(opts, HOME_DIR, SITE_NAME, USER):
    tmpFile = HOME_DIR + 'georef.json'
    factsFile = '/etc/facter/facts.d/georef.json'
    factsDir = os.path.dirname(factsFile)
    if not os.path.exists(factsDir):
        dosys('sudo mkdir -p %s' % factsDir)

    factObj = {
        'site': SITE_NAME,
        'user': USER,
        'dev_instance': (opts.type == 'development'),
    }
    with open(tmpFile, 'w') as f:
        f.write(json.dumps(factObj, indent=4, sort_keys=True))
        f.write('\n')
    dosys('sudo mv %s %s' % (tmpFile, factsFile))


def runPuppet(site):
    siteDeployDir = os.path.realpath(os.path.dirname(__file__))
    siteModulePath = '%s/modules' % siteDeployDir
    ctx = {
        #'baseDeployDir': baseDeployDir,
        'siteDeployDir': siteDeployDir,
        'siteModulePath': siteModulePath,
    }

    logging.info('')
    logging.info('######################################################################')
    logging.info('')
    dosys('sudo puppet apply --modulepath=%(siteModulePath)s %(siteDeployDir)s/manifests/site.pp'
          % ctx)


def setup(opts, SITE_NAME, HOME_DIR, GDS_DIR, USER):
    if opts.type == 'auto':
        insideVagrantGuest = os.path.isdir('/vagrant')
        opts.type = 'development' if insideVagrantGuest else 'production'

    logging.info('Deploying installation of type %s...', opts.type)

    os.chdir(HOME_DIR)
    symlinkDeployRepo(SITE_NAME + '_deploy', PUPPET_DIR)
    installPuppet()
    found = linkExistingSource(SITE_NAME, GDS_DIR, VAGRANT_DIR)
    if not found:
        checkoutSourceRepo(SITE_NAME, GIT_URL_PREFIX, GDS_DIR)
    setupPuppetFacts(opts, HOME_DIR, SITE_NAME, USER)
    runPuppet(SITE_NAME)


def main(SITE_NAME, GIT_URL_PREFIX, HOME_DIR, GDS_DIR, USER, PUPPET_DIR, VAGRANT_DIR):
    import optparse
    parser = optparse.OptionParser('usage: %prog OPTS\n' + __doc__)
    parser.add_option('--type',
                      choices=['development', 'production', 'auto'],
                      default='auto',
                      help='Specify type of installation to deploy [%default]')
    opts, args = parser.parse_args()
    if args:
        parser.error('expected no args')

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    setup(opts, SITE_NAME, HOME_DIR, GDS_DIR, USER)


if __name__ == '__main__':
    import os
    import sys
    import logging
    import tempfile
    import json
    import subprocess

    SITE_NAME = 'georef'
    GIT_URL_PREFIX = 'https://babelfish.arc.nasa.gov/git/'
    HOME_DIR = os.path.expanduser('~') + '/'
    GDS_DIR = HOME_DIR + 'gds/'
    USER = os.getenv('USER')
    PUPPET_DIR = HOME_DIR + 'puppet/'
    VAGRANT_DIR = '/vagrant'

    main(SITE_NAME, GIT_URL_PREFIX, HOME_DIR, GDS_DIR, USER, PUPPET_DIR, VAGRANT_DIR)
