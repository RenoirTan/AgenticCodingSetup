#!/usr/bin/env python3

import logging
import os
import shlex
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from subprocess import PIPE, STDOUT, Popen
from typing import Literal

import yaml

REPO_ROOT = Path(__file__).parent.absolute()
LOGS_DIR = REPO_ROOT / "log"
UNIVERSAL_DIR = REPO_ROOT / "universal"
UNIVERSAL_CONFIG_DIR = UNIVERSAL_DIR / "config" / "v2" / ".agents"
OPENCODE_DIR = REPO_ROOT / "opencode"
OPENCODE_CONFIG_DIR = OPENCODE_DIR / "config" / "v2" / "opencode"

UNIVERSAL_CONFIG_SRC = Path(UNIVERSAL_CONFIG_DIR)
UNIVERSAL_CONFIG_DEST = Path("/home/agent/.agents")

SBX3_UNIVERSAL_DIR = UNIVERSAL_DIR / "sbx3"
SBX3_UNIVERSAL_KITS_DIR = SBX3_UNIVERSAL_DIR / "kits"
SBX3_DDGSMIXIN_DIR = SBX3_UNIVERSAL_KITS_DIR / "ddgs-mixin"
SBX3_DDGSMIXIN_YAML = SBX3_DDGSMIXIN_DIR / "ddgs-mixin.yaml"

SBX_OPENCODE_DIR = OPENCODE_DIR / "sbx"
SBX_OPENCODE_KITS_DIR = SBX_OPENCODE_DIR / "kits"
# SBX_OPENCODE_CONFIGS_DIR = SBX_OPENCODE_DIR / "config" / "v2"
SBX_OPENCODE_KIT_SRC = SBX_OPENCODE_KITS_DIR / "opencode-kit-v2"
SBX_OPENCODE_KIT_DEST = Path("/home/agent/sandbox/opencode/kit")
SBX_OPENCODE_CONFIG_SRC = OPENCODE_CONFIG_DIR
SBX_OPENCODE_CONFIG_DEST = Path("/home/agent/sandbox/opencode/config")
# SBX_OPENCODE_CONFIG_DEST = Path("/home/agent/.config/opencode")
SBX_OPENCODE_BUILD_ARGS = SBX_OPENCODE_DIR / "build-args.sbxoc.yaml"
SBX_OPENCODE_COMPOSE = SBX_OPENCODE_DIR / "docker-compose.sbxoc.yaml"
SBX_OPENCODE_BUILD_ENV = SBX_OPENCODE_DIR / ".env"
SBX_OPENCODE_TEMPLATES_DIR = SBX_OPENCODE_DIR / "templates"

SBX3_OPENCODE_DIR = OPENCODE_DIR / "sbx3"
SBX3_OPENCODE_KITS_DIR = SBX3_OPENCODE_DIR / "kits"
SBX3_OPENCODE_SET_DIR = SBX3_OPENCODE_KITS_DIR / "sbx3oc-set"
SBX3_OPENCODE_SET_YAML = SBX3_OPENCODE_SET_DIR / "sbx3oc-set.yaml"
SBX3_OPENCODE_BUILD_ARGS = SBX3_OPENCODE_DIR / "build-args.sbx3oc.yaml"

MSB_OPENCODE_DIR = OPENCODE_DIR / "msb"
MSB_OPENCODE_COMPOSE = MSB_OPENCODE_DIR / "docker-compose.msboc.yaml"
MSB_OPENCODE_BUILD_ARGS = MSB_OPENCODE_DIR / "build-args.msboc.yaml"
MSB_OPENCODE_BUILD_ENV = MSB_OPENCODE_DIR / ".env"
MSB_OPENCODE_TEMPLATES_DIR = MSB_OPENCODE_DIR / "templates"
MSB_OPENCODE_CONFIG_SRC = OPENCODE_CONFIG_DIR


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    log_formatter = logging.Formatter(
        "%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.warning("Could not make logs dir", exc_info=True)
    else:
        try:
            file_handler = logging.FileHandler(
                LOGS_DIR / f"{datetime.now(tz=UTC).isoformat()}.log"
            )
            file_handler.setFormatter(log_formatter)
            file_handler.setLevel(logging.DEBUG)
            logger.addHandler(file_handler)
        except Exception:
            logger.warning("Could not create log file", exc_info=True)

    return logger


logger = _setup_logging()


class AcsSetup(StrEnum):
    SBX_OPENCODE = "sbx_opencode"
    SBX3_OPENCODE = "sbx3_opencode"
    MSB_OPENCODE = "msb_opencode"


ACS_SETUP_ALIASES: dict[AcsSetup, set[str]] = {
    AcsSetup.SBX_OPENCODE: {
        str(AcsSetup.SBX_OPENCODE),
        "sbxoc",
    },
    AcsSetup.SBX3_OPENCODE: {
        str(AcsSetup.SBX3_OPENCODE),
        "sbx3oc",
    },
    AcsSetup.MSB_OPENCODE: {
        str(AcsSetup.MSB_OPENCODE),
        "msboc",
    },
}

ACS_SETUP_ALIASES_REV: dict[str, AcsSetup] = {
    a: k for k, v in ACS_SETUP_ALIASES.items() for a in v
}


class AcsCommand(StrEnum):
    PREPARE = "prepare"
    UNPREPARE = "unprepare"
    BUILD = "build"


@dataclass
class AcsDirLink:
    src: str
    dest: str
    opts: Literal["ro", "rw"] = field(default="rw")

    @property
    def src_path(self) -> Path:
        return Path(self.src)

    @property
    def dest_path(self) -> Path:
        return Path(self.dest)

    @classmethod
    def parse_dir(cls, dir: str):
        components = dir.split(":")
        n = len(components)
        if n == 1:
            return {"src": components[0], "dest": components[0]}
        elif n == 2:
            return {"src": components[0], "dest": components[1]}
        elif n == 3:
            return {
                "src": components[0],
                "dest": components[1],
                "opts": components[2],
            }
        else:
            raise ValueError(f"Invalid dir: {dir}")

    @classmethod
    def _from_dict(cls, d: dict[str, str]) -> AcsDirLink:
        return cls(**d)  # ty: ignore[invalid-argument-type]

    @classmethod
    def parse_dir_links(cls, dirs: Iterable[str]) -> list[AcsDirLink]:
        return [cls._from_dict(cls.parse_dir(d)) for d in dirs]

    def link(self, pretend: bool = False):
        src_path = self.src_path.absolute()
        dest_path = self.dest_path.absolute()
        if dest_path.exists():
            if dest_path.is_symlink() and src_path.resolve() == dest_path.resolve():
                logger.info(f"{src_path} already linked to {dest_path}")
                return
            else:
                raise FileExistsError(
                    f"{dest_path} already being used for something else"
                )
        else:
            logger.info(f"Linking {dest_path} to {src_path}")
            if not pretend:
                dest_path.symlink_to(src_path)

    def unlink(self, pretend: bool = False):
        src_path = self.src_path.absolute()
        dest_path = self.dest_path.absolute()
        if dest_path.exists():
            if dest_path.is_symlink() and src_path.resolve() == dest_path.resolve():
                logger.info(f"Unlinking {dest_path}")
                if not pretend:
                    dest_path.unlink(missing_ok=True)
            else:
                raise FileExistsError(f"{dest_path} being used for something else")
        else:
            logger.warning(f"{dest_path} is missing, skipping unlink")


@dataclass
class AcsCmdConfig:
    command: AcsCommand
    setup: AcsSetup
    dirs: list[str] = field(default_factory=list)
    pretend: bool = field(default=False)
    unlink_config: bool = field(default=False)
    tag: str = field(default="")


def _make_argparser() -> ArgumentParser:
    parser = ArgumentParser(description="set up your system for your agent harness")
    common_parent = ArgumentParser(add_help=False)
    _ = common_parent.add_argument(
        "-d",
        "--dir",
        dest="dir",
        action="append",
        help="Additional directories to mount",
    )
    _ = common_parent.add_argument(
        "-n",
        "--dry-run",
        "--pretend",
        dest="pretend",
        action="store_true",
        help="Perform a dry run",
    )
    _ = common_parent.add_argument(
        metavar="SETUP",
        dest="setup",
        choices=list(ACS_SETUP_ALIASES_REV.keys()),
        help="Select an agent setup",
    )

    cmd_subparsers = parser.add_subparsers(dest="command", required=True)

    _prepare_parser = cmd_subparsers.add_parser(
        str(AcsCommand.PREPARE),
        parents=[common_parent],
        help="Prepare system for agent harness",
    )
    unprepare_parser = cmd_subparsers.add_parser(
        str(AcsCommand.UNPREPARE),
        parents=[common_parent],
        help="Undo prepare",
    )
    _ = unprepare_parser.add_argument(
        "-U",
        "--unlink-config",
        dest="unlink_config",
        action="store_true",
        help="Unlink docker sbx config. Do not use this flag if there are multiple docker sandbox harnesses running at the same time and you want to keep the config linked for them.",
    )

    build_parser = cmd_subparsers.add_parser(
        str(AcsCommand.BUILD),
        parents=[common_parent],
        help="Build image",
    )
    _ = build_parser.add_argument(
        "-t",
        "--tag",
        dest="tag",
        default="",
        help="Image tag",
    )

    return parser


def _parse_namespace(args: Namespace) -> AcsCmdConfig:
    command = AcsCommand(args.command)
    setup = ACS_SETUP_ALIASES_REV[args.setup]
    dirs = args.dir or []
    pretend = args.pretend
    unlink_config = getattr(args, "unlink_config", False)
    tag = getattr(args, "tag", "")
    return AcsCmdConfig(
        command=command,
        setup=setup,
        dirs=dirs,
        pretend=pretend,
        unlink_config=unlink_config,
        tag=tag,
    )


def prepare_sbxoc(config: AcsCmdConfig):
    logger.info("Preparing docker sbx opencode")
    dir_links = AcsDirLink.parse_dir_links(config.dirs)
    logger.info("Linking opencode config")
    AcsDirLink(
        src=str(SBX_OPENCODE_KIT_SRC),
        dest=str(SBX_OPENCODE_KIT_DEST),
    ).link(pretend=config.pretend)
    AcsDirLink(
        src=str(SBX_OPENCODE_CONFIG_SRC),
        dest=str(SBX_OPENCODE_CONFIG_DEST),
    ).link(pretend=config.pretend)
    AcsDirLink(
        src=str(UNIVERSAL_CONFIG_SRC),
        dest=str(UNIVERSAL_CONFIG_DEST),
    ).link(pretend=config.pretend)
    logger.info("Linking additional directories")
    for d in dir_links:
        d.link(pretend=config.pretend)

    unprepare_shcmd = list(sys.argv)
    unprepare_shcmd[sys.argv.index(str(AcsCommand.PREPARE))] = str(AcsCommand.UNPREPARE)
    unprepare_shlex = shlex.join(map(shlex.quote, unprepare_shcmd))

    create_shcmd = ["sbx", "create", "opencode", "--kit", str(SBX_OPENCODE_KIT_DEST)]
    for d in dir_links:
        create_shcmd.append(str(d.dest_path))
    create_shcmd.append(str(SBX_OPENCODE_CONFIG_DEST))
    create_shcmd.append(str(UNIVERSAL_CONFIG_DEST))
    create_shlex = shlex.join(map(shlex.quote, create_shcmd))

    output = f"""# You may find the following commands helpful
# To source these command variables, do source <(./acs.py ...)
# Then for example, acs_unprepare -U

# Unlink config
acs_unprepare() {{
  {unprepare_shlex} $@
}}

# Create the harness
acs_create() {{
  {create_shlex} $@
}}"""
    print(output)
    if not sys.stdout.isatty():
        print(output, file=sys.stderr)


def prepare_sbx3oc(config: AcsCmdConfig):
    logger.info("Preparing docker sbx3 opencode")
    dir_links = AcsDirLink.parse_dir_links(config.dirs)
    logger.info("Linking opencode config")
    AcsDirLink(
        src=str(SBX_OPENCODE_CONFIG_SRC),
        dest=str(SBX_OPENCODE_CONFIG_DEST),
    ).link(pretend=config.pretend)
    AcsDirLink(
        src=str(UNIVERSAL_CONFIG_SRC),
        dest=str(UNIVERSAL_CONFIG_DEST),
    ).link(pretend=config.pretend)
    logger.info("Linking additional directories")
    for d in dir_links:
        d.link(pretend=config.pretend)

    unprepare_shcmd = list(sys.argv)
    unprepare_shcmd[sys.argv.index(str(AcsCommand.PREPARE))] = str(AcsCommand.UNPREPARE)
    unprepare_shlex = shlex.join(map(shlex.quote, unprepare_shcmd))

    create_shcmd = ["sbx", "create", "opencode", "--kit", str(SBX3_OPENCODE_SET_DIR)]
    for d in dir_links:
        create_shcmd.append(str(d.dest_path))
    create_shcmd.append(str(SBX_OPENCODE_CONFIG_DEST))
    create_shcmd.append(str(UNIVERSAL_CONFIG_DEST))
    create_shlex = shlex.join(map(shlex.quote, create_shcmd))

    output = f"""# You may find the following commands helpful
# To source these command variables, do source <(./acs.py ...)
# Then for example, acs_unprepare -U

# Unlink config
acs_unprepare() {{
  {unprepare_shlex} $@
}}

# Create the harness
acs_create() {{
  {create_shlex} $@
}}"""
    print(output)
    if not sys.stdout.isatty():
        print(output, file=sys.stderr)


def prepare_msboc(config: AcsCmdConfig):
    logger.warning("Preparing microsandbox opencode is not implemented")
    config_mount = shlex.quote(
        f"{MSB_OPENCODE_CONFIG_SRC}:/home/agent/.config/opencode:rw"
    )
    output = f"""# Example: create the microsandbox
acs_create() {{
  msb create \\
    --name opencode \\
    --replace \\
    --cpus 2 \\
    --memory 2G \\
    --root-disk 4G \\
    --mount-dir "$PWD:/home/agent/project:rw" \\
    --workdir /home/agent/project \\
    --mount-dir {config_mount} \\
    msboc "$@"
}}

# Run OpenCode in the created sandbox
acs_exec() {{
  msb exec -t opencode -- opencode "$@"
}}"""
    print(output)
    if not sys.stdout.isatty():
        print(output, file=sys.stderr)


def unprepare_sbxoc(config: AcsCmdConfig):
    logger.info("Unpreparing docker sbx opencode")
    dir_links = AcsDirLink.parse_dir_links(config.dirs)
    if config.unlink_config:
        logger.info("Unlinking opencode config")
        AcsDirLink(
            src=str(SBX_OPENCODE_KIT_SRC),
            dest=str(SBX_OPENCODE_KIT_DEST),
        ).unlink(pretend=config.pretend)
        AcsDirLink(
            src=str(SBX_OPENCODE_CONFIG_SRC),
            dest=str(SBX_OPENCODE_CONFIG_DEST),
        ).unlink(pretend=config.pretend)
    logger.info("Unlinking additional directories")
    for d in dir_links:
        d.unlink(pretend=config.pretend)


def unprepare_sbx3oc(config: AcsCmdConfig):
    logger.info("Unpreparing docker sbx3 opencode")
    dir_links = AcsDirLink.parse_dir_links(config.dirs)
    if config.unlink_config:
        logger.info("Unlinking opencode config")
        AcsDirLink(
            src=str(SBX_OPENCODE_CONFIG_SRC),
            dest=str(SBX_OPENCODE_CONFIG_DEST),
        ).unlink(pretend=config.pretend)
    logger.info("Unlinking additional directories")
    for d in dir_links:
        d.unlink(pretend=config.pretend)


def unprepare_msboc(config: AcsCmdConfig):
    logger.warning("Unpreparing microsandbox opencode is not implemented")


def build_sbxoc(config: AcsCmdConfig):
    logger.info(f"Building sbxoc:{config.tag or 'latest'}")
    os.chdir(SBX_OPENCODE_DIR)
    with SBX_OPENCODE_BUILD_ARGS.open("r") as baf:
        logger.debug(f"Opening {SBX_OPENCODE_BUILD_ARGS}")
        build_args = yaml.load(baf, Loader=yaml.CLoader)
    ba_configs = build_args.get("configs")
    if type(ba_configs) is not list:
        raise ValueError(f"Bad {SBX_OPENCODE_BUILD_ARGS}")
    build_config = None
    if config.tag:
        for bc in ba_configs:
            if bc["tag"] == config.tag:
                build_config = bc
                break
    else:
        build_config = ba_configs[0]
    if build_config is None:
        raise ValueError(f"Could not find sbxoc:{config.tag}")
    logger.debug(f"Found config for {build_config['tag']}")
    build_env = [
        f"{k}={shlex.quote(v)}\n" for k, v in build_config["environment"].items()
    ]
    dockerfile = build_config.get("dockerfile")
    if dockerfile is not None:
        build_env.append(f"DOCKERFILE={dockerfile}\n")
    build_env.append(f"SBXOC_VERSION={build_config['tag']}\n")
    with SBX_OPENCODE_BUILD_ENV.open("w") as bef:
        logger.info(f"Writing config for {build_config['tag']} in .env")
        bef.writelines(build_env)

    build_cmd = [
        "docker",
        "compose",
        "-f",
        str(SBX_OPENCODE_COMPOSE.absolute()),
        "--env-file",
        str(SBX_OPENCODE_BUILD_ENV.absolute()),
        "build",
    ]
    logger.info(f"$ {shlex.join(map(shlex.quote, build_cmd))}")
    build_process = Popen(build_cmd, stdout=PIPE, stderr=STDOUT)
    if build_process.stdout:
        for line in build_process.stdout:
            logger.info(line.decode(encoding="utf-8").rstrip())
    else:
        logger.info("No output from docker build")
    build_ret = build_process.wait()
    if build_ret != 0:
        raise ChildProcessError(f"docker build returned {build_ret}")
    logger.info("Build successful")

    image_name = f"sbxoc:{build_config['tag']}"
    image_shname = shlex.quote(image_name)
    template_path = SBX_OPENCODE_TEMPLATES_DIR / f"{image_name}.tar"
    template_shpath = shlex.quote(str(template_path))
    output = f"""# Run the following commands to export and use the image.

# Save image locally
acs_save_image() {{
  docker image save {image_shname} -o {template_shpath}
  echo Saved image to {template_shpath}
}}

# Import image into sbx
acs_load_template() {{
  sbx template load {template_shpath}
}}

# Create sandbox with custom image
acs_create_custom_sandbox() {{
  sbx create --template {image_shname} opencode
}}"""

    print(output)
    if not sys.stdout.isatty():
        print(output, file=sys.stderr)


def build_sbx3oc(config: AcsCmdConfig):
    logger.info(f"Building sbx3oc:{config.tag or 'latest'}")
    with SBX3_OPENCODE_BUILD_ARGS.open("r") as baf:
        logger.debug(f"Opening {SBX3_OPENCODE_BUILD_ARGS}")
        build_args = yaml.load(baf, Loader=yaml.CLoader)
    ba_configs = build_args.get("configs")
    if type(ba_configs) is not list:
        raise ValueError(f"Bad {SBX3_OPENCODE_BUILD_ARGS}")
    build_config = None
    if config.tag:
        for bc in ba_configs:
            if bc["tag"] == config.tag:
                build_config = bc
                break
    else:
        build_config = ba_configs[0]
    if build_config is None:
        raise ValueError(f"Could not find sbx3oc:{config.tag}")
    logger.debug(f"Found config for {build_config['tag']}")

    build_environment = build_config["environment"]

    ddgs_image_name = f"docker.io/renoirtan/ddgs-mixin:{build_environment['DDGS_TAG']}"

    logger.info(f"Building renoirtan/ddgs-mixin:{build_environment['DDGS_TAG']}")
    ddgs_build_cmd = [
        "docker",
        "buildx",
        "build",
        str(SBX3_DDGSMIXIN_DIR.absolute()),
        "-f",
        str(SBX3_DDGSMIXIN_YAML.absolute()),
        "-t",
        ddgs_image_name,
        "--build-arg",
        f"DDGS_BRANCH={build_environment['DDGS_BRANCH']}",
    ]
    logger.info(f"$ {shlex.join(map(shlex.quote, ddgs_build_cmd))}")
    ddgs_build_process = Popen(ddgs_build_cmd, stdout=PIPE, stderr=STDOUT)
    if ddgs_build_process.stdout:
        for line in ddgs_build_process.stdout:
            logger.info(line.decode(encoding="utf-8").rstrip())
    else:
        logger.info("No output from docker buildx build")
    ddgs_build_ret = ddgs_build_process.wait()
    if ddgs_build_ret != 0:
        raise ChildProcessError(f"docker buildx build returned {ddgs_build_ret}")
    logger.info("Build successful")

    set_image_name = f"renoirtan/sbx3oc-set:{build_config['tag']}"
    logger.info(f"Building {set_image_name}")
    set_build_cmd = [
        "docker",
        "buildx",
        "build",
        str(SBX3_OPENCODE_SET_DIR.absolute()),
        "-f",
        str(SBX3_OPENCODE_SET_YAML.absolute()),
        "-t",
        set_image_name,
    ]
    logger.info(f"$ {shlex.join(map(shlex.quote, set_build_cmd))}")
    ddgs_build_process = Popen(set_build_cmd, stdout=PIPE, stderr=STDOUT)
    if ddgs_build_process.stdout:
        for line in ddgs_build_process.stdout:
            logger.info(line.decode(encoding="utf-8").rstrip())
    else:
        logger.info("No output from docker buildx build")
    set_build_ret = ddgs_build_process.wait()
    if set_build_ret != 0:
        raise ChildProcessError(f"docker buildx build returned {set_build_ret}")
    logger.info("Build successful")

    set_image_shname = shlex.quote(set_image_name)
    output = f"""# Run the following commands to export and use the image.

# Create an opencode sandbox
acs_create_sandbox() {{
    sbx create opencode --kit {set_image_shname} "$@"
}}"""

    print(output)
    if not sys.stdout.isatty():
        print(output, file=sys.stderr)


def build_msboc(config: AcsCmdConfig):
    logger.info(f"Building msboc:{config.tag or 'latest'}")
    os.chdir(MSB_OPENCODE_DIR)
    with MSB_OPENCODE_BUILD_ARGS.open("r") as baf:
        logger.debug(f"Opening {MSB_OPENCODE_BUILD_ARGS}")
        build_args = yaml.load(baf, Loader=yaml.CLoader)
    ba_configs = build_args.get("configs")
    if type(ba_configs) is not list:
        raise ValueError(f"Bad {MSB_OPENCODE_BUILD_ARGS}")
    build_config = None
    if config.tag:
        for bc in ba_configs:
            if bc["tag"] == config.tag:
                build_config = bc
                break
    else:
        build_config = ba_configs[0]
    if build_config is None:
        raise ValueError(f"Could not find msboc:{config.tag}")
    logger.debug(f"Found config for {build_config['tag']}")
    build_env = [
        f"{k}={shlex.quote(v)}\n" for k, v in build_config["environment"].items()
    ]
    build_env.append(f"MBSOC_VERSION={build_config['tag']}\n")
    dockerfile = build_config.get("dockerfile")
    if dockerfile is not None:
        build_env.append(f"DOCKERFILE={dockerfile}\n")
    with MSB_OPENCODE_BUILD_ENV.open("w") as bef:
        logger.info(f"Writing config for {build_config['tag']} in .env")
        bef.writelines(build_env)

    build_cmd = [
        "docker",
        "compose",
        "-f",
        str(MSB_OPENCODE_COMPOSE.absolute()),
        "--env-file",
        str(MSB_OPENCODE_BUILD_ENV.absolute()),
        "build",
    ]
    logger.info(f"$ {shlex.join(map(shlex.quote, build_cmd))}")
    build_process = Popen(build_cmd, stdout=PIPE, stderr=STDOUT)
    if build_process.stdout:
        for line in build_process.stdout:
            logger.info(line.decode(encoding="utf-8").rstrip())
    else:
        logger.info("No output from docker build")
    build_ret = build_process.wait()
    if build_ret != 0:
        raise ChildProcessError(f"docker build returned {build_ret}")
    logger.info("Build successful")

    image_name = f"msboc:{build_config['tag']}"
    image_shname = shlex.quote(image_name)
    MSB_OPENCODE_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    template_path = MSB_OPENCODE_TEMPLATES_DIR / f"{image_name}.tar"
    template_shpath = shlex.quote(str(template_path))
    output = f"""# Run the following commands to export and use the image.

# Save image locally
acs_save_image() {{
  docker image save {image_shname} -o {template_shpath}
  echo Saved image to {template_shpath}
}}

# Import image into microsandbox
acs_load_image() {{
  msb load --input {template_shpath}
}}"""

    print(output)
    if not sys.stdout.isatty():
        print(output, file=sys.stderr)


def prepare(config: AcsCmdConfig):
    match config.setup:
        case AcsSetup.SBX_OPENCODE:
            return prepare_sbxoc(config)
        case AcsSetup.SBX3_OPENCODE:
            return prepare_sbx3oc(config)
        case AcsSetup.MSB_OPENCODE:
            return prepare_msboc(config)
        case _:
            raise ValueError(f"Unknown command: {config.setup}")


def unprepare(config: AcsCmdConfig):
    match config.setup:
        case AcsSetup.SBX_OPENCODE:
            return unprepare_sbxoc(config)
        case AcsSetup.SBX3_OPENCODE:
            return unprepare_sbx3oc(config)
        case AcsSetup.MSB_OPENCODE:
            return unprepare_msboc(config)
        case _:
            raise ValueError(f"Unknown command: {config.setup}")


def build(config: AcsCmdConfig):
    match config.setup:
        case AcsSetup.SBX_OPENCODE:
            return build_sbxoc(config)
        case AcsSetup.SBX3_OPENCODE:
            return build_sbx3oc(config)
        case AcsSetup.MSB_OPENCODE:
            return build_msboc(config)
        case _:
            raise ValueError(f"Unknown command: {config.setup}")


def run(config: AcsCmdConfig):
    match config.command:
        case AcsCommand.PREPARE:
            return prepare(config)
        case AcsCommand.UNPREPARE:
            return unprepare(config)
        case AcsCommand.BUILD:
            return build(config)
        case _:
            raise ValueError(f"Unknown command: {config.command}")


def main():
    args = _make_argparser().parse_args()
    config = _parse_namespace(args)
    logger.debug(config)
    run(config)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.error("An error occurred", exc_info=True)  # ruff: ignore[G201]
