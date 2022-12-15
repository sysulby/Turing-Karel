"""
This file defines the GUI for running Karel programs.

Original Author: Nicholas Bowman
Credits: Kylie Jue, Tyler Yep
License: MIT
Version: 1.0.0
Email: nbowman@stanford.edu
Date of Creation: 10/1/2019
"""
from __future__ import annotations

import importlib.util
import inspect
import pygame as pg
import traceback as tb
from pathlib import Path
from time import sleep
from tkinter.filedialog import askopenfilename
from tkinter.messagebox import showwarning
from types import FrameType, ModuleType
from typing import Any, Callable, cast

from .didyoumean import add_did_you_mean
from .karel_world import Direction
from .karel_program import KarelException, KarelProgram


class StudentModule(ModuleType):
    move: Any
    turn_left: Any
    put_beeper: Any
    pick_beeper: Any
    paint_corner: Any

    @staticmethod
    def main() -> None:
        raise NotImplementedError


class StudentCode:
    """
    This process extracts a module from an arbitary file that contains student code.
    https://stackoverflow.com/questions/67631/how-to-import-a-module-given-the-full-path
    """

    def __init__(self, code_file: Path) -> None:
        if not code_file.is_file():
            raise FileNotFoundError(f"{code_file} could not be found.")

        self.module_name = code_file.stem
        spec = importlib.util.spec_from_file_location(
            self.module_name, code_file.resolve()
        )
        assert spec is not None
        try:
            module_loader = spec.loader
            assert module_loader is not None
            mod = cast(StudentModule, importlib.util.module_from_spec(spec))
            self.mods: list[StudentModule] = [mod]
            module_loader.exec_module(mod)
            # Go through attributes to find imported modules
            for name in dir(mod):
                module = cast(StudentModule, getattr(mod, name))
                if isinstance(module, ModuleType):
                    assert module.__file__ is not None
                    code_file_path = Path(module.__file__)
                    # Only execute modules outside of this directory
                    if code_file_path.parent != Path(__file__).resolve().parent:
                        self.mods.append(module)
                        spec = importlib.util.spec_from_file_location(
                            name, code_file_path.resolve()
                        )
                        module_loader.exec_module(module)
        except SyntaxError as e:
            # Since we don't start the GUI until after we parse the student's code,
            # SyntaxErrors behave normally. However, if the syntax error is somehow
            # not caught at parse time, we should forward the error message to console.
            print(e)
            raise

        # Do not proceed if the student has not defined a main function.
        if not hasattr(self.mods[0], "main"):
            raise RuntimeError(
                "Couldn't find the main() function. Are you sure you have one?"
            )

    def __repr__(self) -> str:
        return "\n".join([inspect.getsource(mod) for mod in self.mods])

    def inject_namespace(self, karel: KarelProgram) -> None:
        """
        This function is responsible for doing some Python hackery
        that associates the generic commands the student wrote in their
        file with specific commands relating to the Karel object that exists
        in the world.
        """
        functions_to_override = [
            "move",
            "turn_left",
            "pick_beeper",
            "put_beeper",
            "facing_north",
            "facing_south",
            "facing_east",
            "facing_west",
            "not_facing_north",
            "not_facing_south",
            "not_facing_east",
            "not_facing_west",
            "front_is_clear",
            "beepers_present",
            "no_beepers_present",
            "beepers_in_bag",
            "no_beepers_in_bag",
            "front_is_blocked",
            "left_is_blocked",
            "left_is_clear",
            "right_is_blocked",
            "right_is_clear",
            "paint_corner",
            "corner_color_is",
        ]
        for mod in self.mods:
            for func in functions_to_override:
                setattr(mod, func, getattr(karel, func))

    def main(self) -> None:
        try:
            self.mods[0].main()
        except Exception as e:
            if isinstance(e, (KarelException, NameError, RuntimeError)):
                self.print_error_traceback(e)
            raise e

    def print_error_traceback(
        self, e: KarelException | NameError | RuntimeError
    ) -> None:
        """Handle runtime errors while executing student code."""
        display_frames: list[tuple[FrameType, int]] = []
        # Walk through all the frames in stack trace at time of failure
        for frame, lineno in tb.walk_tb(e.__traceback__):
            frame_info = inspect.getframeinfo(frame)
            # Get the name of the file corresponding to the current frame
            # Only display frames generated within the student's code
            if Path(frame_info.filename).name == f"{self.module_name}.py":
                display_frames.append((frame, lineno))

        display_frames_generator = (frame for frame in display_frames)
        trace = tb.format_list(tb.StackSummary.extract(display_frames_generator))
        clean_traceback = "".join(trace).strip()
        add_did_you_mean(e)
        print(
            f"Traceback (most recent call last):\n{clean_traceback}\n"
            f"{type(e).__name__}: {e}"
        )


class KarelApplication():
    def __init__(
        self,
        karel: KarelProgram,
        code_file: Path,
        window_width: int = 800,
        window_height: int = 600,
    ) -> None:
        self.karel = karel
        self.world = karel.world
        self.code_file = code_file
        self.load_student_code()
        if not self.student_code.mods:
            pg.quit()
            return
        self.speed = self.world.init_speed

        pg.display.set_caption(self.student_code.module_name)
        pg.display.set_icon(pg.image.load(Path(__file__).absolute().parent / "icon.png"));
        self.screen = pg.display.set_mode((window_width, window_height))
        self.themes = Path(__file__).absolute().parent / "themes/default"
        self.bg = pg.image.load(self.themes / "background.png")
        self.tree = pg.image.load(self.themes / "tree.png")
        self.gem = pg.image.load(self.themes / "gem.png")
        self.hero = {
            Direction.EAST: pg.image.load(self.themes / "right.png"),
            Direction.SOUTH: pg.image.load(self.themes / "down.png"),
            Direction.WEST: pg.image.load(self.themes / "left.png"),
            Direction.NORTH: pg.image.load(self.themes / "up.png")
        }
        self.redraw_all()

    def mainloop(self) -> None:
        while True:
            for event in pg.event.get():
                if event.type == pg.QUIT:
                    exit()
                if event.type == pg.KEYDOWN:
                    if event.key == pg.K_SPACE:
                        self.reset_world()
                        self.run_program()
                    if event.key == pg.K_ESCAPE:
                        self.load_world()
            pg.display.update()

    def redraw_all(self) -> None:
        # background
        self.screen.blit(self.bg, (0, 0))
        # bounding
        x_offset = (20 - self.world.num_avenues) // 2
        y_offset = (15 - self.world.num_streets) // 2
        for x in range(20):
            for y in range(15):
                if x < x_offset or x >= x_offset + self.world.num_avenues or \
                   y < y_offset or y >= y_offset + self.world.num_streets:
                    self.screen.blit(self.tree, (x * 40, y * 40))
        # walls
        for wall in self.world.walls:
            corner_x = (wall.avenue - 1 + x_offset) * 40
            corner_y = (self.world.num_streets - wall.street + y_offset) * 40
            if wall.direction == Direction.NORTH:
                pg.draw.line(self.screen, (63, 63, 63), \
                    (corner_x, corner_y), (corner_x + 40, corner_y), width = 5)
            if wall.direction == Direction.SOUTH:
                pg.draw.line(self.screen, (63, 63, 63), \
                    (corner_x, corner_y + 40), (corner_x + 40, corner_y + 40), width = 5)
            if wall.direction == Direction.EAST:
                pg.draw.line(self.screen, (63, 63, 63), \
                    (corner_x + 40, corner_y), (corner_x + 40, corner_y + 40), width = 5)
            if wall.direction == Direction.WEST:
                pg.draw.line(self.screen, (63, 63, 63), \
                    (corner_x, corner_y), (corner_x, corner_y + 40), width = 5)
        # beepers
        for location, count in self.world.beepers.items():
            if count != 0:
                corner_x = (location[0] - 1 + x_offset) * 40
                corner_y = (self.world.num_streets - location[1] + y_offset) * 40
                self.screen.blit(self.gem, (corner_x, corner_y))
        # karel
        corner_x = (self.karel.avenue - 1 + x_offset) * 40
        corner_y = (self.world.num_streets - self.karel.street + y_offset) * 40
        self.screen.blit(self.hero[self.karel.direction], (corner_x, corner_y))
        pg.display.update()

    def load_student_code(self) -> None:
        self.student_code = StudentCode(self.code_file)
        self.student_code.inject_namespace(self.karel)
        self.inject_decorator_namespace()

    def karel_action_decorator(
        self, karel_fn: Callable[..., None]
    ) -> Callable[..., None]:
        def wrapper() -> None:
            # execute Karel function
            karel_fn()
            # redraw canvas with updated state of the world
            self.redraw_all()
            # delay by specified amount
            sleep(1 - self.speed / 100)

        return wrapper

    def beeper_action_decorator(
        self, karel_fn: Callable[..., None]
    ) -> Callable[..., None]:
        def wrapper() -> None:
            # execute Karel function
            karel_fn()
            # redraw canvas with updated state of the world
            self.redraw_all()
            # delay by specified amount
            sleep(1 - self.speed / 100)

        return wrapper

    def corner_action_decorator(
        self, karel_fn: Callable[..., None]
    ) -> Callable[..., None]:
        def wrapper(color: str) -> None:
            # execute Karel function
            karel_fn(color)
            # redraw canvas with updated state of the world
            self.redraw_all()
            # delay by specified amount
            sleep(1 - self.speed / 100)

        return wrapper

    def inject_decorator_namespace(self) -> None:
        """
        This function is responsible for doing some Python hackery
        that associates the generic commands the student wrote in their
        file with specific commands relating to the Karel object that exists
        in the world.
        """
        for mod in self.student_code.mods:
            mod.turn_left = self.karel_action_decorator(self.karel.turn_left)
            mod.move = self.karel_action_decorator(self.karel.move)
            mod.pick_beeper = self.beeper_action_decorator(self.karel.pick_beeper)
            mod.put_beeper = self.beeper_action_decorator(self.karel.put_beeper)
            mod.paint_corner = self.corner_action_decorator(self.karel.paint_corner)

    def run_program(self) -> None:
        # Error checking for existence of main function completed in prior file

        # reimport code in case it changed
        self.load_student_code()
        try:
            self.student_code.main()

        except (KarelException, NameError):
            # Generate popup window to let the user know their program crashed
            pg.display.update()
            showwarning(
                "Karel Error", "Karel Crashed!\nCheck the terminal for more details."
            )

    def reset_world(self) -> None:
        self.karel.reset_state()
        self.world.reset_world()
        self.redraw_all()

    def load_world(self) -> None:
        default_worlds_path = Path(__file__).absolute().parent / "worlds"
        filename = askopenfilename(
            initialdir=default_worlds_path,
            title="Select Karel World",
            filetypes=[("Karel Worlds", "*.w")],
        )
        # User hit cancel and did not select file, so leave world as-is
        if filename == "":
            return
        self.world.reload_world(filename=filename)
        self.karel.reset_state()
        self.redraw_all()
