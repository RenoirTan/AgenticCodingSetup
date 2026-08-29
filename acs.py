#!/usr/bin/env python3

from argparse import ArgumentParser, Namespace
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import logging
import os
from pathlib import Path
from typing import Dict, Set, List, Literal, Iterable
import shlex
from subprocess import Popen, PIPE, STDOUT
import sys
import yaml


REPO_ROOT = Path(__file__).parent.absolute()
LOGS_DIR = REPO_ROOT / "log"
OPENCODE_DIR = REPO_ROOT / "opencode"
SBX_OPENCODE_DIR = OPENCODE_DIR / "sbx"
SBX_OPENCODE_KIT_SRC = SBX_OPENCODE_DIR / "env-opencode-kit"
SBX_OPENCODE_KIT_DEST = Path("/tmp/opencode-kit")
SBX_OPENCODE_CONFIG_SRC = SBX_OPENCODE_DIR / "my-opencode-kit" / "files" / "home"
SBX_OPENCODE_CONFIG_DEST = Path("/tmp/opencode-config")
SBX_OPENCODE_BUILD_ARGS = SBX_OPENCODE_DIR / "build-args.sbxoc.yaml"
SBX_OPENCODE_COMPOSE = SBX_OPENCODE_DIR / "docker-compose.sbxoc.yaml"
SBX_OPENCODE_BUILD_ENV = SBX_OPENCODE_DIR / ".env"
SBX_OPENCODE_TEMPLATES_DIR = SBX_OPENCODE_DIR / "templates"


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
    except:
        logger.warning("Could not make logs dir", exc_info=True)
    else:
        try:
            file_handler = logging.FileHandler(
                LOGS_DIR / f"{datetime.now().isoformat()}.log"
            )
            file_handler.setFormatter(log_formatter)
            file_handler.setLevel(logging.DEBUG)
            logger.addHandler(file_handler)
        except:
            logger.warning("Could not create log file", exc_info=True)

    return logger


logger = _setup_logging()


class AcsSetup(StrEnum):
    SBX_OPENCODE = "sbx_opencode"


ACS_SETUP_ALIASES: Dict[AcsSetup, Set[str]] = {
    AcsSetup.SBX_OPENCODE: {
        str(AcsSetup.SBX_OPENCODE),
        "sbxoc",
    },
}

ACS_SETUP_ALIASES_REV: Dict[str, AcsSetup] = dict(
    [(a, k) for k, v in ACS_SETUP_ALIASES.items() for a in v]
)


class AcsCommand(StrEnum):
    PREPARE = "prepare"
    UNPREPARE = "unprepare"
    BUILD = "build"


@dataclass
class AcsDirLink:
    src: str
    dest: str
    opts: Literal["ro"] | Literal["rw"] = field(default="rw")

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
    def parse_dir_links(cls, dirs: Iterable[str]) -> List["AcsDirLink"]:
        return [cls(**cls.parse_dir(d)) for d in dirs]

    def link(self, *args, pretend: bool = False, **kwargs):
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

    def unlink(self, *args, pretend: bool = False, **kwargs):
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
    dirs: List[str] = field(default_factory=list)
    pretend: bool = field(default=False)
    unlink_config: bool = field(default=False)
    tag: str = field(default="")


def _make_argparser() -> ArgumentParser:
    parser = ArgumentParser(description="Set up your system for your agent harness")
    common_parent = ArgumentParser(add_help=False)
    common_parent.add_argument(
        "-d",
        "--dir",
        dest="dir",
        action="append",
        help="Additional directories to mount",
    )
    common_parent.add_argument(
        "-n",
        "--dry-run",
        "--pretend",
        dest="pretend",
        action="store_true",
        help="Perform a dry run",
    )
    common_parent.add_argument(
        metavar="SETUP",
        dest="setup",
        choices=list(ACS_SETUP_ALIASES_REV.keys()),
        help="Select an agent setup",
    )

    cmd_subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = cmd_subparsers.add_parser(
        str(AcsCommand.PREPARE),
        parents=[common_parent],
        help="Prepare system for agent harness",
    )
    unprepare_parser = cmd_subparsers.add_parser(
        str(AcsCommand.UNPREPARE),
        parents=[common_parent],
        help="Undo prepare",
    )
    unprepare_parser.add_argument(
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
    build_parser.add_argument(
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
    dirs = args.dir
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
    for line in build_process.stdout:
        logger.info(line.decode(encoding="utf-8").rstrip())
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


def prepare(config: AcsCmdConfig):
    match config.setup:
        case AcsSetup.SBX_OPENCODE:
            return prepare_sbxoc(config)
        case _:
            raise ValueError(f"Unknown command: {config.setup}")


def unprepare(config: AcsCmdConfig):
    match config.setup:
        case AcsSetup.SBX_OPENCODE:
            return unprepare_sbxoc(config)
        case _:
            raise ValueError(f"Unknown command: {config.setup}")


def build(config: AcsCmdConfig):
    match config.setup:
        case AcsSetup.SBX_OPENCODE:
            return build_sbxoc(config)
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
        logger.error("An error occurred", exc_info=True)
