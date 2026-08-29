# AgenticCodingSetup

This repository stores my configs and scripts for agentic coding or vibe coding however you want to call it.

```bash
./acs.py prepare sbxoc --dir $HOME/project:/tmp/project
```

```bash
./acs.py build sbxoc --tag 1.18.10-1 # runs: docker build -t custom-opencode:latest ./opencode/sbx/
docker image save custom-opencode:latest -o ./opencode/sbx/templates/custom-opencode.tar
sbx template load ./opencode/sbx/templates/custom-opencode.tar
sbx create --template custom-opencode:latest opencode
```
