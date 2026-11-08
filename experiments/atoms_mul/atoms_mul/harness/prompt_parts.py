"""Shared learner-visible prompt sections; track-specific language stays in each renderer."""


def library_section(enabled, library, save_on, save_off):
    if enabled:
        return save_on + "\nLibrary:\n" + (library.listing() or "empty")
    return save_off + "\nLibrary:\nempty"


def task_section(task, examples, feedback, answer):
    previous = "\n".join(feedback) if feedback else "none"
    return ("\nTask: " + task["statement"] + "\nPublic examples: " + examples
            + "\nPrevious attempt feedback: " + previous + "\n" + answer)
