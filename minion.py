import sublime, sublime_plugin
import subprocess

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
			
class MinionClearViewCommand(sublime_plugin.TextCommand):
	def run(self, edit):
		print("Erasing...")
		print(self.view.size())
		self.view.insert(edit, 0, "Hello World!")

class MinionBuildCommand(sublime_plugin.WindowCommand):
	def __init__(self, *args):
		super().__init__(*args)

		self.build_system = None
		self.build_process = None

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
		output = self.window.create_output_panel("exec")
		self.window.run_command("show_panel", { "panel" : "output.exec" })
		output.run_command("minion_clear_view")
		return output

	def run_build(self, build_system):
		print(build_system["name"])

		if self.build_process != None:
			self.build_process.terminate()
			self.build_process = None

		def callback():
			self.build_process = subprocess.Popen(
				build_system["cmd"], 
				stdout = subprocess.PIPE, 
				stderr = subprocess.STDOUT)

			output = self.open_output_panel()
			

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
