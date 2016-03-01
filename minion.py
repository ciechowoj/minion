import sublime, sublime_plugin
import subprocess, re, os, os.path

class KillMasterCommand(sublime_plugin.ApplicationCommand):
	def run(self):
		sublime.status_message("Hello, World!")

def make_build_system_name(system, variant):
	if system.endswith('.'):
		return "{} - {}".format(system[:-1], variant)
	else:
		return "{} - {}".format(system[:], variant)

def expand_variables_ex(value, variables):
	if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
		return sublime.expand_variables(value, variables)
	elif isinstance(value, list):
		return [expand_variables_ex(v, variables) for v in value]
	elif isinstance(value, dict):
		return { k : expand_variables_ex(v, variables) for k, v in value.items() }
	else:
		return value
			
class Panel:
	def __init__(self, view):
		self.view = view

	def __getattr__(self, name):
		return getattr(self.view, name)

	def clear(self):
		self.run_command("minion_clear_view")

	def append(self, text):
		self.run_command("minion_panel_append", { "text" : text })

	@classmethod
	def find_panel(cls, window, name):
		panel = Panel(window.find_output_panel(name))
		window.run_command("show_panel", { "panel" : "output.{}".format(name) })
		return panel

	@classmethod
	def find_exec_panel(cls, window):
		return Panel.find_panel(window, "exec")

class MinionClearViewCommand(sublime_plugin.TextCommand):
	def run(self, edit):
		self.view.erase(edit, sublime.Region(0, self.view.size()))

class MinionPanelAppendCommand(sublime_plugin.TextCommand):
	def run(self, edit, text):
		self.view.insert(edit, self.view.size(), text)

class MinionNextResultCommand(sublime_plugin.WindowCommand):
	def __init__(self, window):
		super().__init__(window)
		self.position = 0

	def run(self, action = None, **kwargs):
		if action == "init":
			self.position = 0
			self.build_system = kwargs["build_system"]
		else:
			panel = Panel.find_exec_panel(self.window)
			file_regex = self.build_system["file_regex"]
			region = panel.find(file_regex, self.position)

			self.position = region.end()
			message = panel.substr(region)

			match = re.match(file_regex, message)
			file = match.group(1)
			line = match.group(2)
			column = match.group(3)

			working_dir = self.build_system["working_dir"]
			basename = "{}:{}:{}".format(file, line, column)
			path = os.path.join(working_dir, basename)

			self.window.open_file(path, sublime.ENCODED_POSITION)
			print("{}({}:{})".format(file, line, column))
			print(file_regex, panel.substr(region))
			

class MinionBuildCommand(sublime_plugin.WindowCommand):
	def __init__(self, *args):
		super().__init__(*args)

		self.build_system = None
		self.build_process = None
		self.build_result_position = None

	def __del__(self):
		if self.build_process:
			self.build_process.terminate()

	def build_systems(self):
		window = self.window
		build_systems_data = self.window.project_data()["build_systems"]
		build_systems_data = expand_variables_ex(build_systems_data, window.extract_variables())

		build_systems = {}

		for data in build_systems_data:
			for key, value in data.items():
				if key == "variants":
					for variant in value:
						build_systems[make_build_system_name(data["name"], variant["name"])] = variant
				else:
					try:
						build_systems[data["name"]][key] = value
					except KeyError:
						build_systems[data["name"]] = { key : value }

		return build_systems

	def open_output_panel(self):
		panel = Panel(self.window.create_output_panel("exec"))
		self.window.run_command("show_panel", { "panel" : "output.exec" })
		panel.clear()
		return panel

	def run_build(self, build_system):
		self.window.run_command("save_all")

		if self.build_process != None:
			self.build_process.terminate()
			self.build_process = None

		def callback():
			self.build_process = subprocess.Popen(
				build_system["cmd"], 
				stdout = subprocess.PIPE, 
				stderr = subprocess.STDOUT)

			self.build_result_position = 0

			panel = self.open_output_panel()
			self.window.run_command("minion_next_result", { "action" : "init", "build_system" : build_system })

			for line in self.build_process.stdout:
				panel.append(line.decode("utf-8"))

		sublime.set_timeout_async(callback, 0)

	def run(self):
		window = self.window

		build_systems = self.build_systems()

		if self.build_system in build_systems:
			self.run_build(build_systems[self.build_system])
		else:
			build_system_names = sorted(list(build_systems.keys()))

			def on_done(index):
				self.build_system = build_system_names[index]
				self.run_build(build_systems[self.build_system])
				
			window.show_quick_panel(build_system_names, on_done)
