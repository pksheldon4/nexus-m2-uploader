 #!/usr/bin/env python3

""""
nexus-uploader.py
Allows mirroring local M2 repositories to a remote Nexus server with a single command.
Supports: 
   - uploading of common classifiers (sources, javadocs) if available
   - using regex include pattern for artifactIds/groupIds
   - recursively processing local repo, just point to the root 
   - only upload artifacts missing on server (with option to force if needed)
"""

import requests
from requests.auth import HTTPBasicAuth
import os
import os.path as path
import sys
import argparse

## Hides warnings for cert issues which can occur if using self-signed certs.
## Have also specified 'verify=False' on the Http calls to skip ssl verification.
import urllib3
urllib3.disable_warnings()

def list_files(root, ffilter = lambda x: True, recurse = True):
    """ list all files matching a filter in a given dir with optional recursion. """
    for root, subdirs, files in os.walk(root):
        for f in filter(ffilter, files):
            yield path.join(root, f)
        if recurse:
            for sdir in subdirs:
                for f in list_files(sdir, ffilter, recurse):
                    yield f

#### This checks for Jars in the m2 folder that don't have accompanying pom files, which would miss them on the primary pass.
def check_for_orphaned_jars(repo_url, repo_id, auth, root) :
  print("Check for Orphaned Jars: ", root)
  for jar in list_files(root, lambda x: x.endswith(".jar") and not x.endswith("-sources.jar") and not x.endswith("-javadoc.jar")):
      rpath = path.dirname(jar).replace(root, '')
      rpath_parts = list(filter(lambda x: x != '', rpath.split(os.sep)))
      file_name = path.basename(jar)
      groupId = '.'.join(rpath_parts[:-2])
      artifactId = rpath_parts[-2:-1][0]
      version = rpath_parts[-1:][0]
      m2_path = "%s/%s/%s/%s" % (groupId.replace('.','/'), artifactId, version, file_name)

      if not artifact_exists(repo_url, repo_id, auth, m2_path):
        payload = { 'hasPom':'true', 'repository':repo_id }
        files = {
          'maven2.groupId': (None, groupId),
          'maven2.artifactId': (None, artifactId),
          'maven2.version': (None, version),
          'maven2.asset1': (file_name, open(jar, 'rb')),
          'maven2.asset1.extension': (None, 'jar'),
        } 
        #Note: There's no way to identify an arch classifier without a pom file.
        url = "%s/%s" % (repo_url, 'service/rest/v1/components')
        req = requests.post(url, allow_redirects = False, files=files, auth=auth, params=payload, timeout = 20, verify=False)        
        if req.status_code > 299:
          print ("Error communicating with Nexus!"),
          print ("code=", str(req.status_code), ", msg=[", req.content,"]", "resource=",file_name)
        else:
          print ("Successfully uploaded: ", file_name)



def m2_maven_info(root):
    """ walks an on-disk m2 repo yielding a dict of pom/gav/jar info. """
    for pom in list_files(root, lambda x: x.endswith(".pom")):
        rpath = path.dirname(pom).replace(root, '')
        rpath_parts = list(filter(lambda x: x != '', rpath.split(os.sep)))
        info = { 'path': path.dirname(pom), 'pom': path.basename(pom) }
        info['groupId'] = '.'.join(rpath_parts[:-2])
        info['artifactId'] = rpath_parts[-2:-1][0]
        info['version'] = rpath_parts[-1:][0]
        # check for jar
        jarfile = "" #in case there are no jar files
        for fj in os.listdir(path.dirname(pom)):
          if fj.endswith(".jar") and not fj.endswith("-sources.jar") and  not fj.endswith("-javadoc.jar") :
            jarfile = os.path.join(path.dirname(pom),fj)
            if not jarfile == pom.replace('.pom', '.jar') :
              pomBase = info['pom'].replace(".pom","")
              classifier = fj.replace(pomBase,"").replace(".jar","").lstrip("-")
              if classifier :
                info['classifier'] = classifier

        if path.isfile(jarfile):
            info['jar'] = path.basename(jarfile)
            # check for sources
            sourcejar = jarfile.replace('.jar', '-sources.jar')
            if path.isfile(sourcejar):
                info['source'] = path.basename(sourcejar)
            # check for javadoc
            docjar = jarfile.replace('.jar', '-javadoc.jar')
            if path.isfile(docjar):
                info['docs'] = docjar
        yield info

def nexus_postform(minfo, repo_url, files, auth, form_params, file_name):
    url = "%s/%s" % (repo_url, 'service/rest/v1/components')
    req = requests.post(url, allow_redirects = False, files=files, auth=auth, params=form_params, timeout = 20, verify=False)
    if req.status_code > 299:
        print ("Error communicating with Nexus!"),
        print ("code=", str(req.status_code), ", msg=[", req.content,"]", "resource=",file_name)
    else:
        print ("Successfully uploaded: ", file_name)

def artifact_exists(repo_url, repo_id, auth, artifact_path):
    url = "%s/repository/%s/%s" % (repo_url, repo_id, artifact_path)
    # print ("### Checking for: ", url)
    req = requests.head(url, auth=auth, verify=False)
    if req.status_code == 404:
        # print (url, " Not found.")
        return False
    if req.status_code == 200:
        # print ("Will *NOT* upload", artifact_path, "artifact already exists")
        return True
    else:
        # for safety, return true if we cannot determine if file exists
        print ("Error checking status of: ", basename)
        return True

def last_attached_file(filename, minfo):
    m2_path = "%s/%s/%s" % (minfo['groupId'].replace('.','/'), minfo['artifactId'], minfo['version'])
    return "%s/%s"  % (m2_path, filename)

def nexus_upload(maven_info, repo_url, repo_id, auth=None, force=False):

    payload = { 'hasPom':'true', 'repository':repo_id }
                
    # append file params
    fullpath = path.join(maven_info['path'], maven_info['pom'])
    file_name = maven_info['pom']
    files = {
      'maven2.asset1': (file_name, open(fullpath, 'rb')),
      'maven2.asset1.extension': (None, 'pom'),
    }
    if 'jar' in maven_info:
      asset_name = maven_info['jar']
      fullpath = path.join(maven_info['path'], asset_name)
      classifier = maven_info['classifier'] if 'classifier' in maven_info else ""
      files |= {
        'maven2.asset2': (asset_name, open(fullpath, 'rb')),
        'maven2.asset2.extension': (None, 'jar'),
        'maven2.asset2.classifier': (None, classifier)
      }
                  
    last_artifact = last_attached_file(info['pom'], maven_info)
    if force or not artifact_exists(repo_url, repo_id, auth, last_artifact) :
      nexus_postform(maven_info, repo_url, files=files, auth=auth, form_params=payload, file_name=last_artifact)
    
    if 'source' in maven_info:
      file_name = maven_info['source']
      fullpath = path.join(maven_info['path'], file_name)
      files = {
        'maven2.groupId': (None, maven_info['groupId']),
        'maven2.artifactId': (None, maven_info['artifactId']),
        'maven2.version': (None, maven_info['version']),
        'maven2.asset1': (file_name, open(fullpath, 'rb')),
        'maven2.asset1.extension': (None, 'jar'),
        'maven2.asset1.classifier': (None, 'sources'),
      }            
      last_artifact = last_attached_file(file_name, maven_info)
      if force or not artifact_exists(repo_url, repo_id, auth, last_artifact):
          nexus_postform(maven_info, repo_url, files=files, auth=auth, form_params=payload, file_name=last_artifact)

    if 'docs' in maven_info:
      fullpath = path.join(maven_info['path'], maven_info['docs'])
      files = {
        'maven2.groupId': (None, maven_info['groupId']),
        'maven2.artifactId': (None, maven_info['artifactId']),
        'maven2.version': (None, maven_info['version']),
        'maven2.asset1': (maven_info['docs'], open(fullpath, 'rb')),
        'maven2.asset1.extension': (None, 'jar'),
        'maven2.asset1.classifier': (None, 'javadoc'),
      }            
      last_artifact = last_attached_file(maven_info['docs'], maven_info)
      if force or not artifact_exists(repo_url, repo_id, auth, last_artifact):
          nexus_postform(maven_info, repo_url, files=files, auth=auth, form_params=payload, file_name=last_artifact)

def gav(info):
    return (info['groupId'], info['artifactId'], info['version'], info['classifier'])

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Easily upload multiple artifacts to a remote Nexus server.')
    parser.add_argument('repodirs', type=str, nargs='+',
                        help='list of repodirs to scan')
    parser.add_argument('--repo-id', type=str, help='Repository ID (in Nexus) to u/l to.', required=True)
    parser.add_argument('--auth',type=str, help='basicauth credentials in the form of username:password.')
    parser.add_argument('--include-artifact','-ia', type=str, metavar='REGEX', help='regex to apply to artifactId')
    parser.add_argument('--include-group', '-ig', type=str, metavar='REGEX', help='regex to apply to groupId')
    parser.add_argument('--force-upload', '-F', action='store_true', help='force u/l to Nexus even if artifact exists.')
    parser.add_argument('--repo-url', type=str, required=True, 
                        help="Nexus repo URL (e.g. http://localhost:8081)")


    args = parser.parse_args()
    
    import re
    igroup_pat = None
    iartifact_pat = None
    if args.include_group:
        igroup_pat = re.compile(args.include_group)
    if args.include_artifact:
        iartifact_pat = re.compile(args.include_artifact)
    
    auth = None
    credentials=tuple(args.auth.split(':'))
    if credentials is not None:
      auth = HTTPBasicAuth(credentials[0], credentials[1])

    for repo in args.repodirs:
      print ("Uploading content from [%s] to %s repo on %s" % (repo, args.repo_id, args.repo_url))
      for info in  m2_maven_info(repo):
          # only include specific groups if group regex supplied
          if igroup_pat and not igroup_pat.search(info['groupId']):
              continue

          # only include specific artifact if artifact regex supplied
          if iartifact_pat and not iartifact_pat.search(info['archiveId']):
              continue
          
          # print ("\nProcessing: ", (gav(info)))
          nexus_upload(info, args.repo_url, args.repo_id, auth, force=args.force_upload)
      
      ## check for jarfiles without accompanying pom files. These may need to be uploaded manually
      check_for_orphaned_jars(args.repo_url, args.repo_id, auth, repo)        
