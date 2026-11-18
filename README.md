# AgenticCodingSetup

This repository stores my configs and scripts for agentic coding or vibe coding however you want to call it.

## Docker SBX

Due to sbx's current instability (I have had to rewrite ./acs.py several times over a month), some things may not work even a week from now.

You will notice an `sbx3` and maybe an `sbx` version for each agent. This is because of the change from sbx kits v1/v2 to kits v3. v3 is not backwards compatible with v1/v2, so I had to separate out both configs. You should only use sbx3oc.

## OpenCode

### sbx3oc

```bash
./acs.py build sbx3oc -t 0.2.0
```

```bash
./acs.py prepare sbx3oc -d $HOME/project:/home/agent/project
```

```bash
sbx create sbx/opencode:2.3.0 --kit /path/to/ACS/opencode/sbx3/kits/sbx3oc-set --kit-arg ddgsTag=9.16.1-3 /home/agent/project
```

### sbxoc

```bash
./acs.py prepare sbxoc --dir $HOME/project:/tmp/project
```

```bash
./acs.py build sbxoc --tag 1.18.10-1 # runs: docker build -t custom-opencode:latest ./opencode/sbx/
docker image save custom-opencode:latest -o ./opencode/sbx/templates/custom-opencode.tar
sbx template load ./opencode/sbx/templates/custom-opencode.tar
sbx create --template custom-opencode:latest opencode
```
