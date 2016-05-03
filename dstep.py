import sublime, sublime_plugin

class ExampleCommand(sublime_plugin.WindowCommand):
	def run(self, edit):
		self.view.insert(edit, 0, "Hello, World!")
