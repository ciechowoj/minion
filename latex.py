import sublime_plugin
from User.build import *


class MinionBuildLatexCommand(sublime_plugin.WindowCommand):
    ignore = [
        "This is ",
        " restricted .write18 enabled",
        "entering extended mode",
        "LaTeX2e <.*>",
        ".*/usr/share/.*(\\.sty|\\.tex|\\.dfu|\\.def|\\.fd|\\.cfg|\\.cls|\\.clo)",
        ".*/usr/share/texlive.*",
        "Babel <.*> and hyphenation patterns for 3 languages",
        "Document Class: ",
        ".*Beta version. Formatting may change",
        ".*in future versions of this class.",
        "Document language package ",
        ".*Switching to Polish text encoding and Polish maths fonts.",
        r"\*geometry\* driver: auto-detecting",
        r"\*geometry\* detected driver: pdftex",
        "ABD: EveryShipout initializing macros",
        r"\[Loading MPS to PDF converter.*\]",
        r"\(/usr/share/texmf/tex/generic/pgf/frontendlayer/tikz/libraries/t",
        r"hs.code.tex\)\)\) \(.*\)"
    ]

    def latex_data(self):
        project_data = self.window.project_data()

        if "latex" not in project_data:
            panel = Panel.request_exec_panel(self.window)
            panel.append('[Error: "latex" not present in project settings]')

        latex_data = project_data["latex"]

        if "main" not in latex_data:
            panel = Panel.request_exec_panel(self.window)
            panel.append('[Error: main file not specified (e.g. "main": "main.tex")]')

        return expand_variables_ex(latex_data)

    def filter(self, panel, lines, config):
        verbose = "verbose" in config and config["verbose"]

        if not verbose:
            ignore = False

            for item in MinionBuildLatexCommand.ignore:
                if re.match(item, lines[-1]) != None:
                    ignore = True
                    break

            if ignore:
                pass
            elif lines[-1].startswith("(./{}".format(config["main"])):
                pass
            else:
                panel.append('{}'.format(lines[-1]))

    def on_finished(self, panel, return_code, elapsed_time, config):
        pass

    def run(self):
        latex_data = self.latex_data()

        latex_data["command"] = ["pdflatex", latex_data["main"]]

        MinionGenericBuildCommand.run_build(latex_data, self.filter)

