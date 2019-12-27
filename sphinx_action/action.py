import collections
import subprocess
import tempfile
import os
import shlex

from sphinx_action import status_check


GithubEnvironment = collections.namedtuple(
    'GithubEnvironment', ['sha', 'repo', 'token', 'build_command']
)


def extract_line_information(line_information):
    file_and_line = line_information.split(':')
    # This is a dirty windows specific hack to deal with drive letters in the
    # start of the file-path, i.e D:\
    if len(file_and_line[0]) == 1:
        # If the first component is just one letter, we did an accindetal split
        file_and_line[1] = file_and_line[0] + ':' + file_and_line[1]
        # Join the first component back up with the second and discard it.
        file_and_line = file_and_line[1:]

    if len(file_and_line) != 2 and len(file_and_line) != 3:
        return None
    # The case where we have no line number, in this case we return the line
    # number as 1 to mark the whole file.
    if len(file_and_line) == 2:
        line_num = 1
    if len(file_and_line) == 3:
        try:
            line_num = int(file_and_line[1])
        except ValueError:
            return None

    file_name = os.path.relpath(file_and_line[0])
    return file_name, line_num


def parse_sphinx_warnings_log(logs):
    """Parses a sphinx file containing warnings and errors into a list of
    status_check.CheckAnnotation objects.

    Inputs look like this:
/media/sf_shared/workspace/sphinx-action/tests/test_projects/warnings_and_errors/index.rst:19: WARNING: Error in "code-block" directive:
maximum 1 argument(s) allowed, 2 supplied.

/cpython/Doc/distutils/_setuptools_disclaimer.rst: WARNING: document isn't included in any toctree
/cpython/Doc/contents.rst:5: WARNING: toctree contains reference to nonexisting document 'ayylmao'
    """ # noqa
    annotations = []

    for i, line in enumerate(logs):
        if 'WARNING' not in line:
            continue

        warning_tokens = line.split('WARNING:')
        if len(warning_tokens) != 2:
            continue
        file_and_line, message = warning_tokens

        file_and_line = extract_line_information(file_and_line)
        if not file_and_line:
            continue
        file_name, line_number = file_and_line

        warning_message = message
        # If this isn't the last line and the next line isn't a warning,
        # treat it as part of this warning message.
        if (i != len(logs) - 1) and 'WARNING' not in logs[i + 1]:
            warning_message += logs[i + 1]
        warning_message = warning_message.strip()

        annotations.append(status_check.CheckAnnotation(
            path=file_name, message=warning_message,
            start_line=line_number, end_line=line_number,
            annotation_level=status_check.AnnotationLevel.WARNING
        ))

    return annotations


def build_docs(build_command, docs_directory):
    if not build_command:
        raise ValueError("Build command may not be empty")

    docs_requirements = os.path.join(docs_directory, 'requirements.txt')
    if os.path.exists(docs_requirements):
        subprocess.check_call(['pip', 'install', '-r', docs_requirements])

    log_file = os.path.join(tempfile.gettempdir(), 'sphinx-log')
    if os.path.exists(log_file):
        os.unlink(log_file)

    sphinx_options = '--keep-going --no-color -w "{}"'.format(log_file)
    # If we're using make, pass the options as part of the SPHINXOPTS
    # environment variable, otherwise pass them straight into the command.
    build_command = shlex.split(build_command)
    
    if build_command[0] == 'make':
        print("Test1")
        return_code = subprocess.call(
            build_command,
            env=dict(os.environ, SPHINXOPTS=sphinx_options),
            cwd=docs_directory
        )
    else:
        print("Test2")
        return_code = subprocess.call(
            build_command + shlex.split(sphinx_options),
            cwd=docs_directory
        )
    
    print(os.system("ls"))
    with open(log_file, 'r') as f:
        annotations = parse_sphinx_warnings_log(f.readlines())

    return return_code, annotations


def build_all_docs(github_env, docs_directories):
    if len(docs_directories) == 0:
        raise ValueError("Please provide at least one docs directory to build")

    # Optionally, if they've provided us with a GITHUB_TOKEN, we output
    # warnings to the status check.
    if github_env.token:
        status_id = status_check.create_in_progress_status_check(
            github_env.token, github_env.sha, github_env.repo)
        print("[sphinx-action] Created check with id={}".format(status_id))

    build_success = True
    warnings = 0

    for docs_dir in docs_directories:
        print("====================================")
        print("Building docs in {}".format(docs_dir))
        print("====================================")

        return_code, annotations = build_docs(
            github_env.build_command, docs_dir
        )
        if return_code != 0:
            build_success = False

        warnings += len(annotations)

        if github_env.token:
            check_output = status_check.CheckOutput(
                title='Sphinx Documentation Build',
                summary='Building with {} warnings'.format(warnings),
                annotations=annotations
            )
            print("[sphinx-action] Updating status check with ", check_output)
            status_check.update_status_check(
                status_id, github_env.token, github_env.repo, check_output
            )

    status_message = 'Build {} with {} warnings'.format(
        'succeeded' if build_success else 'failed', warnings)
    print(status_message)

    if github_env.token:
        check_output = status_check.CheckOutput(
            title='Sphinx Documentation Build',
            summary=status_message, annotations=[]
        )
        conclusion = status_check.StatusConclusion.from_build_succeeded(
            build_success)
        status_check.update_status_check(
            status_id, github_env.token, github_env.repo, check_output,
            conclusion=conclusion)

    if not build_success:
        raise RuntimeError("Build failed")
