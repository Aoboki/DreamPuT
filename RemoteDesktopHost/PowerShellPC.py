
import subprocess
import threading
import queue
import os
import time


# ============================================================
# REMOTE POWERSHELL PROCESS
#
# Этот модуль управляет одним постоянным PowerShell.exe.
#
# ВАЖНО:
#
# execute() НЕ ждёт завершения команды.
#
# PowerShell.exe работает постоянно.
#
# Вывод читается отдельным потоком и складывается
# в output_queue.
#
# host.py регулярно забирает данные через get_output().
# ============================================================


class PowerShellProcess:

    def __init__(self):

        # ----------------------------------------------------
        # PowerShell process
        # ----------------------------------------------------

        self.process = None

        self.running = False

        # ----------------------------------------------------
        # Output queue
        #
        # Сюда reader thread складывает весь вывод.
        # ----------------------------------------------------

        self.output_queue = queue.Queue()

        self.reader_thread = None

        # ----------------------------------------------------
        # Command state
        # ----------------------------------------------------

        self.command_running = False

        self.command_id = 0

        # ----------------------------------------------------
        # Thread lock
        # ----------------------------------------------------

        self.lock = threading.RLock()


    # ========================================================
    # START POWERSHELL
    # ========================================================

    
    def start(self):
        with self.lock:
            if self.process is not None:
                try:
                    if self.process.poll() is None:
                        self.running = True
                        return True
                except Exception:
                    pass

            print()
            print("=" * 60)
            print("      Remote PowerShell")
            print("=" * 60)
            print()
            print("▶ Starting PowerShell...")

            self.process = None
            self.running = False
            self.command_running = False
            self.command_id = 0

            if os.name != "nt":
                print()
                print("❌ PowerShellPC is designed for Windows")
                return False

            try:
                # Hidden window — user does not see PowerShell UI
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0  # SW_HIDE

                create_no_window = getattr(
                    subprocess, "CREATE_NO_WINDOW", 0x08000000
                )

                self.process = subprocess.Popen(
                    [
                        "powershell.exe",
                        "-NoLogo",
                        "-NoProfile",
                        "-WindowStyle", "Hidden",
                        "-ExecutionPolicy", "Bypass",
                        "-NoExit",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    startupinfo=startupinfo,
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP
                        | create_no_window
                    ),
                    cwd=os.getcwd(),
                )

                self.running = True
                self.command_running = False

                # === КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ ===
                # Принудительно заставляем PowerShell вывести что-то,
                # иначе reader висит, а сайт остаётся на Starting...
                init_commands = [
                    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
                    "$OutputEncoding = [System.Text.Encoding]::UTF8",
                    "Write-Host '=== POWERSHELL READY ===' -ForegroundColor Green",
                    # Можно добавить ещё:
                    # "Write-Host (Get-Location).Path",
                ]

                for cmd in init_commands:
                    self.process.stdin.write(cmd + "\n")
                self.process.stdin.flush()

                # Запускаем reader
                self.reader_thread = threading.Thread(
                    target=self._reader,
                    daemon=True,
                    name="PowerShellReader",
                )
                self.reader_thread.start()

                print()
                print("🟢 PowerShell started")
                print(f"   PID: {self.process.pid}")
                print()
                return True

            except Exception as e:
                print()
                print("❌ Failed to start PowerShell")
                print(f"   {type(e).__name__}: {e}")
                self.process = None
                self.running = False
                self.command_running = False
                return False


    # ========================================================
    # READER THREAD
    #
    # PowerShell stdout постоянно читается здесь.
    #
    # НИКОГДА не читаем stdout из execute().
    # ========================================================

    def _reader(self):

        print()
        print(
            "📖 PowerShell output reader started"
        )


        process = self.process


        try:

            if process is None:

                return


            while True:

                # ------------------------------------------------
                # Проверяем, существует ли процесс
                # ------------------------------------------------

                if self.process is not process:

                    break


                # ------------------------------------------------
                # Читаем одну строку
                #
                # readline() блокируется до появления строки.
                # Это нормально — reader является отдельным
                # daemon thread.
                # ------------------------------------------------

                line = process.stdout.readline()


                # ------------------------------------------------
                # PowerShell завершился
                # ------------------------------------------------

                if line == "":

                    try:

                        if process.poll() is not None:

                            break

                    except Exception:

                        break

                    continue


                # ------------------------------------------------
                # Передаём строку в очередь
                # ------------------------------------------------

                self.output_queue.put(

                    {
                        "type":
                            "stdout",

                        "output":
                            line,
                    }

                )


                # ------------------------------------------------
                # Также выводим в консоль host.py
                # ------------------------------------------------

                print(
                    f"PS OUTPUT: "
                    f"{line.rstrip()}"
                )


        except Exception as e:

            print()
            print(
                "❌ PowerShell reader error"
            )

            print(
                f"   {type(e).__name__}: {e}"
            )


        finally:

            exit_code = None

            try:

                exit_code = process.poll()

            except Exception:

                pass


            # ------------------------------------------------
            # PowerShell завершился
            # ------------------------------------------------

            with self.lock:

                self.running = False

                self.command_running = False


            # ------------------------------------------------
            # Передаём событие host.py
            # ------------------------------------------------

            self.output_queue.put(

                {
                    "type":
                        "finished",

                    "exit_code":
                        exit_code,
                }

            )


            print()
            print(
                "🔴 PowerShell output reader stopped"
            )

            print(
                f"   Exit code: {exit_code}"
            )


    # ========================================================
    # EXECUTE COMMAND
    #
    # НЕ ждём результат.
    #
    # Команда просто отправляется в stdin.
    #
    # Вывод позже появляется в output_queue.
    # ========================================================

    def execute(self, command):

        # ----------------------------------------------------
        # Проверяем PowerShell
        # ----------------------------------------------------

        if not self.is_running():

            return {

                "success":
                    False,

                "error":
                    "PowerShell is not running",

            }


        # ----------------------------------------------------
        # Проверяем команду
        # ----------------------------------------------------

        if command is None:

            return {

                "success":
                    False,

                "error":
                    "PowerShell command is empty",

            }


        if not isinstance(
            command,
            str
        ):

            command = str(
                command
            )


        command = command.strip()


        if not command:

            return {

                "success":
                    False,

                "error":
                    "PowerShell command is empty",

            }


        # ----------------------------------------------------
        # Получаем process
        # ----------------------------------------------------

        with self.lock:

            process = self.process

            if process is None:

                self.running = False

                return {

                    "success":
                        False,

                    "error":
                        "PowerShell process unavailable",

                }


            # ------------------------------------------------
            # Проверяем процесс
            # ------------------------------------------------

            try:

                if process.poll() is not None:

                    self.running = False

                    self.command_running = False

                    return {

                        "success":
                            False,

                        "error":
                            "PowerShell process has exited",

                    }

            except Exception as e:

                return {

                    "success":
                        False,

                    "error":
                        str(e),

                }


            # ------------------------------------------------
            # Новый command ID
            # ------------------------------------------------

            self.command_id += 1

            current_command_id = (
                self.command_id
            )

            self.command_running = True


        print()
        print("=" * 60)
        print(
            "💻 EXECUTING POWERSHELL COMMAND"
        )

        print(
            f"   ID: {current_command_id}"
        )

        print(
            f"   Command: {command}"
        )

        print("=" * 60)


        # ----------------------------------------------------
        # Отправляем команду
        # ----------------------------------------------------

        try:

            process.stdin.write(
                command + "\n"
            )

            process.stdin.flush()


            print(
                "📤 Command sent to PowerShell"
            )


            # ------------------------------------------------
            # НЕ читаем stdout здесь.
            #
            # stdout читает _reader().
            # ------------------------------------------------

            return {

                "success":
                    True,

                "command_id":
                    current_command_id,

            }


        except Exception as e:

            with self.lock:

                self.command_running = False


            print()
            print(
                "❌ PowerShell execute error"
            )

            print(
                f"   {type(e).__name__}: {e}"
            )


            return {

                "success":
                    False,

                "error":
                    f"{type(e).__name__}: {e}",

            }


    # ========================================================
    # GET OUTPUT
    #
    # Возвращает ВСЕ накопившиеся сообщения.
    #
    # host.py вызывает эту функцию регулярно.
    # ========================================================

    def get_output(self):

        result = []


        while True:

            try:

                item = (
                    self.output_queue.get_nowait()
                )


            except queue.Empty:

                break


            if item is None:

                continue


            result.append(
                item
            )


        return result


    # ========================================================
    # STOP CURRENT COMMAND
    #
    # PowerShell.exe остаётся запущенным.
    # ========================================================

    def stop_command(self):

        if not self.is_running():

            return False


        process = self.process


        if process is None:

            return False


        print()
        print(
            "⏹ Stopping current PowerShell command..."
        )


        success = False


        # ----------------------------------------------------
        # Windows
        # ----------------------------------------------------

        if os.name == "nt":

            # ------------------------------------------------
            # Сначала CTRL+BREAK
            # ------------------------------------------------

            try:

                process.send_signal(
                    subprocess.CTRL_BREAK_EVENT
                )

                print(
                    "📤 CTRL_BREAK_EVENT sent"
                )

                success = True

            except Exception as e:

                print(
                    "⚠️ CTRL_BREAK_EVENT failed:"
                )

                print(
                    f"   {e}"
                )


                # --------------------------------------------
                # Запасной вариант
                # --------------------------------------------

                try:

                    process.stdin.write(
                        "\x03"
                    )

                    process.stdin.flush()

                    success = True

                except Exception as e2:

                    print(
                        "⚠️ CTRL+C fallback failed:"
                    )

                    print(
                        f"   {e2}"
                    )


        else:

            try:

                process.stdin.write(
                    "\x03"
                )

                process.stdin.flush()

                success = True

            except Exception:

                pass


        with self.lock:

            self.command_running = False


        # ----------------------------------------------------
        # Сообщение для browser
        # ----------------------------------------------------

        self.output_queue.put(

            {
                "type":
                    "system",

                "output":
                    "⏹ Current command stopped.",

            }

        )


        return success


    # ========================================================
    # STATUS
    # ========================================================

    def is_running(self):

        with self.lock:

            if not self.running:

                return False


            process = self.process


            if process is None:

                self.running = False

                self.command_running = False

                return False


            try:

                if process.poll() is None:

                    return True

            except Exception:

                pass


            self.running = False

            self.command_running = False

            return False


    # ========================================================
    # COMMAND STATUS
    # ========================================================

    def is_command_running(self):

        return (

            self.is_running()

            and

            self.command_running

        )


    # ========================================================
    # STOP POWERSHELL COMPLETELY
    # ========================================================

    def stop(self):

        with self.lock:

            process = self.process

            self.running = False

            self.command_running = False


        if process is None:

            self.process = None

            return True


        print()
        print(
            "🛑 Stopping PowerShell..."
        )


        # ----------------------------------------------------
        # Пытаемся корректно завершить PowerShell
        # ----------------------------------------------------

        try:

            try:

                process.stdin.write(
                    "exit\n"
                )

                process.stdin.flush()

            except Exception:

                pass


            # ------------------------------------------------
            # Ждём завершения
            # ------------------------------------------------

            try:

                process.wait(
                    timeout=3
                )


            except subprocess.TimeoutExpired:

                print(
                    "⚠️ PowerShell did not stop"
                )

                print(
                    "   Killing process..."
                )


                try:

                    process.kill()

                except Exception:

                    pass


                try:

                    process.wait(
                        timeout=3
                    )

                except Exception:

                    pass


        except Exception as e:

            print()
            print(
                "❌ PowerShell stop error"
            )

            print(
                f"   {type(e).__name__}: {e}"
            )


        # ----------------------------------------------------
        # Закрываем pipes
        # ----------------------------------------------------

        try:

            if process.stdin:

                process.stdin.close()

        except Exception:

            pass


        try:

            if process.stdout:

                process.stdout.close()

        except Exception:

            pass


        with self.lock:

            if self.process is process:

                self.process = None

            self.running = False

            self.command_running = False


        print(
            "🔴 PowerShell stopped"
        )


        return True


# ============================================================
# GLOBAL INSTANCE
# ============================================================

powershell = PowerShellProcess()


# ============================================================
# SIMPLE API
# ============================================================

def start():

    return powershell.start()


def execute(command):

    return powershell.execute(
        command
    )


def get_output():

    return powershell.get_output()


def stop_command():

    return powershell.stop_command()


def stop():

    return powershell.stop()


def is_running():

    return powershell.is_running()


def is_command_running():

    return powershell.is_command_running()


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    try:

        if not start():

            raise SystemExit(1)


        print()
        print("=" * 60)
        print(" PowerShell direct test")
        print("=" * 60)
        print()

        print(
            "Commands:"
        )

        print(
            "  hostname"
        )

        print(
            "  ipconfig"
        )

        print(
            "  tasklist"
        )

        print(
            "  Get-Process"
        )

        print(
            "  python -u Monitor.py"
        )

        print()

        print(
            "Special:"
        )

        print(
            "  stopcmd  - stop current command"
        )

        print(
            "  exitpc   - stop PowerShell"
        )

        print()


        while is_running():

            try:

                command = input(
                    "PS> "
                )

            except (
                EOFError,
                KeyboardInterrupt
            ):

                break


            command = command.strip()


            if not command:

                continue


            if command.lower() == "exitpc":

                break


            if command.lower() == "stopcmd":

                stop_command()

                continue


            result = execute(
                command
            )


            if not result.get(
                "success",
                False
            ):

                print(
                    result.get(
                        "error",
                        "Unknown error"
                    )
                )

                continue


            print(
                f"Command ID: "
                f"{result.get('command_id')}"
            )


            # ------------------------------------------------
            # Даём reader thread немного времени
            # ------------------------------------------------

            time.sleep(
                0.2
            )


            output = get_output()


            for item in output:

                item_type = item.get(
                    "type"
                )


                if item_type == "stdout":

                    print(
                        item.get(
                            "output",
                            ""
                        ),
                        end=""
                    )


                elif item_type == "system":

                    print(
                        item.get(
                            "output",
                            ""
                        )
                    )


                elif item_type == "finished":

                    print(
                        f"\nPowerShell finished. "
                        f"Exit code: "
                        f"{item.get('exit_code')}"
                    )


    finally:

        stop()
