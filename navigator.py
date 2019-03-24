import hashlib
import sublime
import sublime_plugin
import ctypes
import _ctypes
import os.path
import os
import tempfile
import shutil
import time

navigator_dl = None
temporary_dir = os.path.join(tempfile.gettempdir(), "navigator-2vdsy32egx")
navigator_object = None
navigator_code_complete_at = None
navigator_unsaved_file_t = None

def compute_hash(filename):
  sha256_hash = hashlib.sha256()
  with open(filename,"rb") as file:
      for block in iter(lambda: file.read(4096), b""):
          sha256_hash.update(block)

      return sha256_hash.hexdigest()


def plugin_loaded():
  global navigator_dl
  global temporary_dir
  global navigator_object
  global navigator_code_complete_at
  global navigator_unsaved_file_t

  navigator_filename = "/home/wojciech/Desktop/haste-os.path/build/lib/libnavigator.so"
  hash = compute_hash(navigator_filename)
  libnavigator_so = os.path.join(temporary_dir, hash + ".so")

  if not os.path.exists(libnavigator_so):
    os.makedirs(temporary_dir, exist_ok = True)
    shutil.copy(navigator_filename, libnavigator_so)

  print(libnavigator_so)
  navigator_dl = ctypes.CDLL(libnavigator_so)

  class RESULT(ctypes.Structure):
    _fields_ = [("ptr", ctypes.POINTER(ctypes.c_char_p)),
                ("len", ctypes.c_ulonglong)]

  class UNSAVED_FILE_T(ctypes.Structure):
    _fields_ = [("filename", ctypes.c_char_p),
                ("content", ctypes.c_char_p),
                ("length", ctypes.c_ulonglong)]

  navigator_unsaved_file_t = UNSAVED_FILE_T

  haste_new_navigator = navigator_dl.haste_new_navigator
  haste_new_navigator.restype = ctypes.c_void_p

  navigator_object = navigator_dl.haste_new_navigator()

  print("Create navigator_object: ", navigator_object)

  navigator_code_complete_at = navigator_dl.haste_navigator_code_complete_at
  navigator_code_complete_at.argtypes = [
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_ulonglong,
    ctypes.c_ulonglong,
    ctypes.POINTER(navigator_unsaved_file_t),
    ctypes.c_ulonglong]

  navigator_code_complete_at.restype = RESULT

  if navigator_object == None:
    print("Unable to create navigator_object.")

def plugin_unloaded():
  global navigator_dl
  global navigator_object
  navigator_dl.haste_del_navigator(navigator_object)
  navigator_object = None

def code_complete_at(filename, line, column, unsaved):
  global navigator_object
  global navigator_code_complete_at
  global navigator_unsaved_file_t

  start = time.time()

  native_unsaved_files = (navigator_unsaved_file_t * len(unsaved))()

  for i in range(len(unsaved)):
    content = unsaved[0][1].encode(encoding = 'UTF-8')
    native_unsaved_files[i].filename = unsaved[0][0].encode(encoding = 'UTF-8')
    native_unsaved_files[i].content = content
    native_unsaved_files[i].length = len(content)

  native_start = time.time()

  native_result = navigator_code_complete_at(
    navigator_object,
    filename.encode(encoding = 'UTF-8'),
    line,
    column,
    native_unsaved_files,
    len(native_unsaved_files))

  print("Completions native call took ", time.time() - start, " seconds.")

  index = 0
  result = []

  for i in range(native_result.len // 2):
    completion = (
      native_result.ptr[i * 2 + 0].decode(encoding = 'UTF-8'),
      native_result.ptr[i * 2 + 1].decode(encoding = 'UTF-8'))

    result.append(completion)

  print("Completions retrieved in ", time.time() - start, " seconds.")

  return result

class CodeCompleteCommand(sublime_plugin.ViewEventListener):
  last_completion = None

  def on_query_completions(self, prefix, locations):
    print(prefix, locations)
    location = locations[0]

    flags = sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS

    last_completion = CodeCompleteCommand.last_completion

    filename = self.view.file_name()
    row, col = self.view.rowcol(location)

    print(last_completion, (filename, row, col - 1))

    if last_completion == (filename, row, col - 1):
      CodeCompleteCommand.last_completion = (filename, row, col)
      return ([], flags)

    if ("source.c++" in self.view.scope_name(location)) and self.validate_colon(location):
      content = self.view.substr(sublime.Region(0, self.view.size()))
      completions = code_complete_at(filename, row + 1, col + 1, [(filename, content)])

      CodeCompleteCommand.last_completion = (filename, row, col)

      return (completions, flags)
    else:
      return ([], flags)

  def validate_colon(self, location):
    if location > 2:
      substr = self.view.substr(sublime.Region(location - 2, location))

      if substr[1] == ':' and substr[0] != ':':
        return False

    return True




