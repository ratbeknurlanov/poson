"""Исполняет модифицированный байткод"""

import sys
from enum import Enum, auto
from threading import Thread, Event
from typing import Text
from types import CodeType
from queue import Queue

from .bytecode_modifier import BytecodeModifier


class DebuggerExit(Exception):
    pass


class DebuggerNotStarted(Exception):
    pass


class EmptySourceCode(Exception):
    pass


class DebugCommand(Enum):
    """
    Команды отладки
    """
    STEP_OVER = auto()
    STEP_IN = auto()
    STEP_OUT = auto


class Debugger:
    """Отладчик"""
    _TRACE_FUNC = 'trace'
    _COMMAND = 'command'

    def __init__(self):
        self._commands = Queue()
        self._snapshots = Queue()
        self._finished = Event()
        self._bytecode_modifier = BytecodeModifier(
            self._TRACE_FUNC, self._COMMAND)

    def start(self, source: Text, filename: Text):
        """
        Запускает отладчик

        Отладка программы запускается в отдельном потоке, следовательно, не
        блокирует вызывающий поток

        :param source: исходный код программы
        :param filename: название файла откуда был прочитан исходный код
        :raise EmptySourceCode: пустой исходный код
        """
        if not source:
            raise EmptySourceCode()

        modified_code = self._compile(source, filename)

        t = Thread(target=self._bootstrap, args=(modified_code, ), daemon=True)
        t.start()

    def send_command(self, command: DebugCommand):
        """
        Отправляет команду отладчику

        :raise DebuggerNotStarted: отладчик не запущен
        """

        self._commands.put(command)

    def get_snapshot(self) -> dict:
        """
        Блокирует вызывающий поток до тех пор, пока не появится новое состояние
        (команды step over, step in, step out) или отладка не завершится
        (команда stop)

        Структура:
            - словарь глобальных переменных
            - словарь локальных переменных
            - номер отлаживаемой строки
        :return: данные о текущем состояний отлаживаемой программы
        :raise DebuggingFinished: при завершении отладки
        """
        snapshot = self._snapshots.get()

        if snapshot is DebuggerExit:
            raise DebuggerExit('Отладка закончена')

        return snapshot

    def finish(self):
        """
        Завершает отладчик

        Вызов данного метода не завершает отладку сразу, а
        отправляет потоку отладки команду завершения.
        Чтобы дождаться полного завершения используйте вызов метода `join`
        """
        self._commands.put(DebuggerExit)

    def join(self):
        """
        Дожидается завершения работы отладчика

        Блокирует вызывающий поток
        """
        self._finished.wait()

    def _compile(self, source: Text, filename: Text) -> CodeType:
        """Компилирует исходный код программы в модифицированный байткод"""
        try:
            code = compile(source, filename, 'exec')
        except (SyntaxError, ValueError) as e:
            raise e

        modified_code = self._bytecode_modifier.modify(code)

        return modified_code

    # все методы ниже выполняются в другом потоке
    # в потоке отладки
    def _bootstrap(self, code):
        try:
            self._run(code)
        except DebuggerExit:
            pass
        finally:
            self._snapshots.put(DebuggerExit)
            self ._finished.set()

    def _run(self, code):
        globals_ = {
            self._TRACE_FUNC: self._trace,
            self._COMMAND: None
        }
        exec(code, globals_)

    def _trace(self):
        frame = sys._getframe(1)
        snapshot = {
            'global_variables': frame.f_globals,
            'local_variables': frame.f_locals,
            'line_no': frame.f_lineno
        }
        self._snapshots.put(snapshot)

        command = self._commands.get()

        if command is DebuggerExit:
            raise DebuggerExit()
