# nexus-m2-uploader

The idea of this repo is to allow the user to upload the files from a local .m2 folder to a nexus repository.

In it's simplest form, you can upload the full contents of a local .m2 repository
```sh
python3 nexus-upload.py .m2/repository --repo-id maven-local --auth admin:$ADMIN_PASS --repo-url https://nexus.example.com
```


An additional option to split dependencies is to use the `nexus-repository-conversion-tool`

The included `pom.xml` file contains a single dependency which can be downloaded using `mvn install`
This `jar` can help by splitting local dependencies into separate releases and snapshots folders

Copy the jar to a work folder, from `~/.m2/repository/org/sonatype/nexus/tools/nexus-repository-conversion-tool/2.2.1` and then run

`java -jar nexus-repository-conversion-tool-2.2.1-cli.jar -r ~/.m2 -o temp` which will produce the following directory structure.
```
└── temp
    ├── .m2-releases
    └── .m2-snapshots
```

If you want a clean m2 folder that is limited to just the dependencies of a specific project, you can build the project using the following command, including the `-Dmaven.repo.local` path

`mvn clean install -Dmaven.repo.local=./m2-local`


_The main nexus-upload.py script was derived from https://gist.github.com/omnisis/9ecae6baf161d19206a5420bddffe1fc and updated for Python3 and Nexus 3._