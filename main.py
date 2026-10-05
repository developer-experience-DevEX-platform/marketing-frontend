import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Any

import typer
from yaml import FullLoader, dump, load

from circleci.common import (
    ACCEPTANCE_TESTS_HEADLESS_JOB_NAME,
    ACCEPTANCE_TESTS_JOB_NAME,
    ACCEPTANCE_TESTS_PLAYWRIGHT_JOB_NAME,
    ANALYTICS_TEST_JOB_NAME,
    ANALYTICS_TEST_MICRO_CHECK,
    DEPLOY_GATE,
    FINAL_JOB_NAME,
    PUSH_JOB_NAME,
    STRESS_TESTS_JOB_NAME,
    WAIT_JOB_NAME,
    get_job_from_workflow,
)
from circleci.jobs import (
    add_analytics_dependency_notice,
    add_cf_worker_build_job,
    add_cf_worker_check_deploy_jobs,
    add_cf_worker_deploy_jobs,
    add_docker_build_and_push_job,
    add_generic_build_job,
    add_generic_deploy_job,
    add_gitops_push_jobs,
    add_kubernetes_render_jobs,
    add_manifest_diff_job,
    add_tests,
    add_verify_cf_worker_secrets_job,
    add_verify_nxt_config_job,
    analytics_test_micro_check,
    create_acceptance_tests,
    create_acceptance_tests_playwright,
    create_stress_tests,
)
from dependency_graph.dependencies import ProjectsPaths, get_dependencies
from ecosia_project.ecosia_project import EcosiaProject, Env, EnvAndRegion, ProjectType, Region
from utils.circleci import get_dev_namespace_name, is_on_main_branch
from utils.node_version import get_node_version_from_nvmrc
from utils.render_helpers import (
    get_docker_tag,
    is_rebuild_required,
    skip_build_and_deploy,
)
from utils.strictos import REPO_ROOT


def get_job_requires(workflow_jobs: list[dict[str, Any]], job_name: str) -> list[Any]:
    job_dict = next(filter(lambda job: job_name in job, workflow_jobs))
    # Add requires if it doesn't exist yet
    result: list[Any] = job_dict[job_name].setdefault("requires", [])
    return result


def _add_generic_project_jobs(
    project: EcosiaProject,
    on_main_branch: bool,
    workflow_jobs: list[dict[str, Any]],
    job_requirements: dict[str, list[str]],
    diff_base: str | None = None,
) -> None:
    """Adds jobs for generic projects to the workflow."""
    if project.build:
        add_generic_build_job(
            on_main_branch=on_main_branch,
            project=project,
            workflow_jobs=workflow_jobs,
            job_requirements=job_requirements,
        )

    if project.envs_to_deploy(on_main_branch) and not project.alerts_only:
        add_generic_deploy_job(
            on_main_branch=on_main_branch,
            project=project,
            workflow_jobs=workflow_jobs,
            job_requirements=job_requirements,
            diff_base=diff_base,
        )


def _add_cloudflare_worker_jobs(
    project: EcosiaProject,
    on_main_branch: bool,
    workflow_jobs: list[dict[str, Any]],
    job_requirements: dict[str, list[str]],
) -> None:
    """Adds jobs for Cloudflare Workers to the workflow."""
    if project.build:
        add_cf_worker_build_job(
            on_main_branch=on_main_branch,
            project=project,
            workflow_jobs=workflow_jobs,
            job_requirements=job_requirements,
        )

    if not on_main_branch:
        add_verify_cf_worker_secrets_job(
            project=project,
            workflow_jobs=workflow_jobs,
            job_requirements=job_requirements,
        )

    if project.envs_to_deploy(on_main_branch):
        add_cf_worker_deploy_jobs(
            on_main_branch=on_main_branch,
            project=project,
            workflow_jobs=workflow_jobs,
            job_requirements=job_requirements,
        )
        if project.health_check is not None:
            add_cf_worker_check_deploy_jobs(
                on_main_branch=on_main_branch,
                project=project,
                workflow_jobs=workflow_jobs,
                job_requirements=job_requirements,
            )


def process(
    ci_template: dict[str, Any],
    workspaces: list[str],
    project_paths: ProjectsPaths,
    stress_tests_target: str = "auto",
    diff_base: str | None = None,
) -> dict[str, Any]:
    config = deepcopy(ci_template)

    on_main_branch = is_on_main_branch()
    workflow_jobs = config["workflows"]["build_deploy"]["jobs"]

    # Mapping of workflow job -> [jobs that it requires].
    job_requirements: dict[str, list[str]] = {
        f"{PUSH_JOB_NAME}-dev": [],
        f"{PUSH_JOB_NAME}-prod": [],
        f"{PUSH_JOB_NAME}-staging": [],
        f"{WAIT_JOB_NAME}-dev": [],
        f"{WAIT_JOB_NAME}-staging": [],
        f"{WAIT_JOB_NAME}-prod": [],
        ANALYTICS_TEST_MICRO_CHECK: [],
        FINAL_JOB_NAME: get_job_requires(workflow_jobs, FINAL_JOB_NAME),
        DEPLOY_GATE: [],
        ACCEPTANCE_TESTS_JOB_NAME: [],
        ACCEPTANCE_TESTS_HEADLESS_JOB_NAME: [],
        ACCEPTANCE_TESTS_PLAYWRIGHT_JOB_NAME: [],
        STRESS_TESTS_JOB_NAME: [],
    }

    for project_path in project_paths.test_only_paths:
        project = EcosiaProject.from_path(path=project_path)
        add_tests(
            on_main_branch=on_main_branch,
            project=project,
            workflow_jobs=workflow_jobs,
            job_requirements=job_requirements,
        )

    # Determine which projects (represented by the path to their
    # ecosia_project.yaml), environments and regions we care about
    # when rendering Kubernetes projects.
    # With this we know which deploy jobs to create.
    # This basically prevents us from creating unnecessary deploy jobs.
    # For example, if we are on main branch, do not create the job `render-dev`
    k8s_deploy_jobs_to_create: dict[EnvAndRegion, set[str]] = {}

    deploys_to_diff: set[str] = set()
    for path in sorted(project_paths.build_and_deploy_paths | project_paths.deploy_only_paths):
        have_to_build_and_deploy = is_rebuild_required(path, project_paths.build_and_deploy_paths)

        if skip_build_and_deploy(path, on_main_branch, project_paths.build_and_deploy_paths):
            # If we do not have to rebuild this project, we can skip building and deploying
            # in staging and prod.
            continue

        project = EcosiaProject.from_path(path=path)

        if have_to_build_and_deploy:
            add_tests(
                on_main_branch=on_main_branch,
                project=project,
                job_requirements=job_requirements,
                workflow_jobs=workflow_jobs,
                add_analytics_test=True,
            )

        if project.project_type == ProjectType.CLOUDFLARE_WORKER:
            _add_cloudflare_worker_jobs(project, on_main_branch, workflow_jobs, job_requirements)

        elif project.project_type == ProjectType.GENERIC:
            _add_generic_project_jobs(
                project, on_main_branch, workflow_jobs, job_requirements, diff_base=diff_base
            )

        elif project.project_type == ProjectType.KUBERNETES:
            docker_tag = get_docker_tag(have_to_build_and_deploy)
            # Only build the image if language and build are both explicitly set
            if project.build and have_to_build_and_deploy:
                add_docker_build_and_push_job(
                    on_main_branch=on_main_branch,
                    project=project,
                    workflow_jobs=workflow_jobs,
                    job_requirements=job_requirements,
                    docker_tag=docker_tag,
                )

            if project.envs_to_deploy(on_main_branch=on_main_branch):
                env_and_regions = project.get_kubernetes_deploy_envs_and_regions(on_main_branch)

                for env_and_region in env_and_regions:
                    if env_and_region not in k8s_deploy_jobs_to_create:
                        k8s_deploy_jobs_to_create[env_and_region] = set()
                    k8s_deploy_jobs_to_create[env_and_region].add(path)

            # NXT projects run config validation on every push (branches and main)
            # to catch missing SSM keys and schema mismatches before and after deployment.
            if project.nxt and have_to_build_and_deploy:
                add_verify_nxt_config_job(
                    project=project,
                    workflow_jobs=workflow_jobs,
                    job_requirements=job_requirements,
                    on_main_branch=on_main_branch,
                )

            # Check if this kubernetes project will deploy to staging and/or prod.
            # If so, we want to see the kubernetes diff for staging/prod on this PR
            if project.deploy.env[Env.STAGING] or project.deploy.env[Env.PROD]:
                deploys_to_diff.add(path)

        if (
            REPO_ROOT / Path(project.path) / "ecosia-alerts.yaml"
        ).is_file() or project.alerts.enableBaseline:
            if on_main_branch:
                eu_central1_prod = EnvAndRegion(Env.PROD, Region.EU_CENTRAL_1)
                if eu_central1_prod not in k8s_deploy_jobs_to_create:
                    k8s_deploy_jobs_to_create[eu_central1_prod] = set()
                k8s_deploy_jobs_to_create[eu_central1_prod].add(str(project.path))
            else:
                deploys_to_diff.add(path)

    for env_and_region, paths in k8s_deploy_jobs_to_create.items():
        projects = [EcosiaProject.from_path(p) for p in paths]
        add_kubernetes_render_jobs(
            projects=projects,
            on_main_branch=on_main_branch,
            deploy_env=env_and_region.env,
            workflow_jobs=workflow_jobs,
            job_requirements=job_requirements,
            deploy_region=env_and_region.region,
            diff_base=diff_base,
        )

    if k8s_deploy_jobs_to_create:
        add_gitops_push_jobs(on_main_branch, workflow_jobs, job_requirements)

    # The deploy gate collects all build/render jobs that must complete before deploy.
    # Ensure the final job also depends on these so CI fails if any build/render fails.
    if on_main_branch and job_requirements[DEPLOY_GATE]:
        job_requirements[FINAL_JOB_NAME] += job_requirements[DEPLOY_GATE]

    if on_main_branch and job_requirements[ACCEPTANCE_TESTS_JOB_NAME]:
        # We ensure the acceptance tests job is created if things need it

        # If there are prod deploy jobs, they have already set all-ok
        # to depend on them
        final_job_require = []
        if not _is_there_cf_prod_deploy_jobs(workflow_jobs) and not _is_there_render_jobs(
            job_requirements[DEPLOY_GATE]
        ):
            # There are no prod deployment jobs.
            # So this is the last job. all-ok should require acceptance-tests
            final_job_require = job_requirements[FINAL_JOB_NAME]

        create_acceptance_tests(
            job_requirements[ACCEPTANCE_TESTS_JOB_NAME],
            workflow_jobs,
            final_job_require,
        )

    if not on_main_branch and stress_tests_target != "auto":
        create_stress_tests(
            job_requirements[STRESS_TESTS_JOB_NAME],
            workflow_jobs,
            next_job_requires=job_requirements[FINAL_JOB_NAME],
            target_env=stress_tests_target,
        )

    if (
        not on_main_branch
        and get_job_from_workflow(workflow_jobs, ANALYTICS_TEST_JOB_NAME)
        and not get_job_from_workflow(workflow_jobs, ANALYTICS_TEST_MICRO_CHECK)
    ):
        job_requirements[ANALYTICS_TEST_MICRO_CHECK].append(f"{WAIT_JOB_NAME}-dev")
        analytics_test_micro_check(
            False,
            job_requirements[ANALYTICS_TEST_MICRO_CHECK],
            workflow_jobs,
            next_job_requires=job_requirements[FINAL_JOB_NAME],
        )

    playwright_requirements = job_requirements[ACCEPTANCE_TESTS_PLAYWRIGHT_JOB_NAME]
    # Tests target dev/staging only: on branches the job needs the PR's k8s
    # namespace,Worker-only PRs also create the job; they select no tests (workers are not
    # in mapping.yaml yet) and exit green until the mapping follow-up lands.
    if playwright_requirements:
        create_acceptance_tests_playwright(
            playwright_requirements,
            workflow_jobs,
            # HEAD^ gets the diff from the previous commit on main when batched
            # deployments are disabled; branches diff against origin/main
            diff_base=diff_base or "",
            test_url=(
                "https://www.ecosia-staging.xyz"
                if on_main_branch
                else f"https://{get_dev_namespace_name(on_main_branch=False)}.www.ecosia-dev.xyz"
            ),
        )

    # The diff job is non-blocking for any other jobs
    if deploys_to_diff and not on_main_branch:
        add_manifest_diff_job(on_main_branch, workflow_jobs)

    # Post a PR comment if any affected project depends on analytics libraries
    if not on_main_branch:
        analytics_dep_names = {"analytics/client-js", "analytics/client-vue2"}
        has_analytics_dependent = False
        for path in sorted(project_paths.build_and_deploy_paths | project_paths.test_only_paths):
            project = EcosiaProject.from_path(path=path)
            build_deps = set(project.buildDependencies or [])
            if project.name in analytics_dep_names or build_deps & analytics_dep_names:
                has_analytics_dependent = True
                break
        if has_analytics_dependent:
            add_analytics_dependency_notice(
                workflow_jobs=workflow_jobs,
                final_job_requires=job_requirements[FINAL_JOB_NAME],
            )

    return config


def _is_there_render_jobs(job_names: list[str]) -> bool:
    return any(job for job in job_names if job.startswith("render-"))


def _is_there_cf_prod_deploy_jobs(workflow_jobs: list[dict[str, Any]]) -> bool:
    cf_prod_deploy_re = re.compile("^deploy-cf-worker-.*-prod$")
    for job in workflow_jobs:
        if re.match(cf_prod_deploy_re, list(job.values())[0].get("name", "")):
            return True
    return False


def load_yaml(yaml_path: Path) -> Any:
    with open(yaml_path, encoding="utf8") as yaml_file:
        return load(yaml_file, Loader=FullLoader)


def update_node_version_in_template(template: dict[str, Any]) -> dict[str, Any]:
    """Update the node_image parameter default value with version from .nvmrc

    Note: The node_image parameter is never overridden at runtime in CircleCI.
    It always uses its default value, so we update the default here to match .nvmrc
    before the configuration is processed by CircleCI.
    """
    node_version = get_node_version_from_nvmrc()
    template["parameters"]["node_image"]["default"] = f"node:{node_version}"
    return template


def update_playwright_image_in_template(template: dict[str, Any]) -> dict[str, Any]:
    """Set playwright_image default from catalog.@playwright/test in pnpm-workspace.yaml."""
    workspace_path = REPO_ROOT / "pnpm-workspace.yaml"
    with open(workspace_path, encoding="utf8") as f:
        data = load(f, Loader=FullLoader)
    version = str((data.get("catalog") or {}).get("@playwright/test", "")).strip()
    if not version:
        raise ValueError(
            f'catalog."@playwright/test" not found in {workspace_path}. '
            "Update pnpm-workspace.yaml when changing the Playwright Docker image."
        )
    template["parameters"]["playwright_image"]["default"] = (
        f"mcr.microsoft.com/playwright:v{version}-noble"
    )
    return template


def load_workspaces(package_json_path: Path) -> Any:
    with open(package_json_path, encoding="utf8") as package_json_file:
        package_json = json.load(package_json_file)
    # Yarn workspaces can either be a list or a nested dict
    workspaces = package_json.get("workspaces", [])
    if isinstance(workspaces, dict):
        return workspaces.get("packages", [])
    return workspaces


default_ci_template = REPO_ROOT / "tools" / "arbor" / "config.template.yml"
default_package_json = REPO_ROOT / "package.json"


def generate_workflow(
    branch: Annotated[
        str,
        typer.Option(
            help="Branch to compare `main` against. If `main` is specified here, "
            "then HEAD^ will be compared against HEAD to cover the case of squash merges to `main`."
        ),
    ],
    ci_template: Annotated[
        Path,
        typer.Option(help="Path to base configuration file", show_default=str(default_ci_template)),
    ] = default_ci_template,
    output: Annotated[str, typer.Option(help="File name of output file")] = "generated_config.yml",
    package_json: Annotated[
        Path,
        typer.Option(
            help="Path to root level package.json", show_default=str(default_package_json)
        ),
    ] = default_package_json,
    stress_tests_target: Annotated[
        str,
        typer.Option(
            help="Target environment for stress tests. "
            "If set, forces stress tests to be executed on PRs [default: auto]",
            show_default="auto",
        ),
    ] = "auto",
    diff_base: Annotated[
        str | None,
        typer.Option(
            help="Override diff base commit for batched deploys. "
            "When set, changed files are computed as diff_base..HEAD instead of the default."
        ),
    ] = None,
) -> None:
    """
    Generates CircleCI workflow configurations

    Can require CIRCLE_SHA1 and CIRCLE_PULL_REQUEST environment variables to be set.

    Here's a quick development command to get it running, it generates the config for
    the current branch:

    ```sh

    CIRCLE_SHA1=$(git rev-parse HEAD) \\

    CIRCLE_PULL_REQUEST=https://github.com/ecosia/core/pull/123456789 \\

    arbor circleci generate-workflow --branch $(git branch --show-current)

    ```
    """
    # We pass around relative project paths so we need to be in the root of the repo!!!
    os.chdir(REPO_ROOT)

    loaded_ci_template = load_yaml(ci_template)
    # Update node_image parameter default to match .nvmrc version
    # Note: This parameter is never overridden at runtime - all Docker images use this default
    loaded_ci_template = update_node_version_in_template(loaded_ci_template)
    loaded_ci_template = update_playwright_image_in_template(loaded_ci_template)
    workspaces = load_workspaces(package_json)

    projectPaths = get_dependencies(branch, diff_base=diff_base)
    print(
        "\n*** to build and deploy ***\n"
        + "\n".join(sorted(projectPaths.build_and_deploy_paths))
        + "\n"
    )
    print("\n*** to deploy only ***\n" + "\n".join(sorted(projectPaths.deploy_only_paths)) + "\n")
    print("\n*** to test only ***\n" + "\n".join(sorted(projectPaths.test_only_paths)) + "\n")

    result = process(
        ci_template=loaded_ci_template,
        workspaces=workspaces,
        project_paths=projectPaths,
        stress_tests_target=stress_tests_target,
        diff_base=diff_base,
    )

    with open(output, "w") as out:
        out.write("# ===\n# Dynamically generated CircleCI config.\n# ===\n\n")
        out.write(dump(result))
        out.write("\n")
