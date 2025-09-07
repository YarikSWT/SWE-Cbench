from typing import Any
import logging
import os

from constants import (
    APPLY_PATCH_FAIL,
    END_TEST_OUTPUT,
    FAIL_ONLY_REPOS,
    FAIL_TO_FAIL,
    FAIL_TO_PASS,
    KEY_INSTANCE_ID,
    KEY_PREDICTION,
    MAP_REPO_VERSION_TO_SPECS,
    PASS_TO_FAIL,
    PASS_TO_PASS,
    RESET_FAILED,
    START_TEST_OUTPUT,
    TESTS_ERROR,
    TESTS_TIMEOUT,
    EvalType,
    ResolvedStatus,
    TestStatus,
)
from test_spec.test_spec import TestSpec
from log_parsers import MAP_REPO_TO_PARSER


# MARK: Utility functions
def test_passed(case: str, sm: dict[str, str]) -> bool:
    return case in sm and sm[case] in [TestStatus.PASSED.value, TestStatus.XFAIL.value]


def test_failed(case: str, sm: dict[str, str]) -> bool:
    return case not in sm or sm[case] in [TestStatus.FAILED.value, TestStatus.ERROR.value]


def get_error_patterns_for_repo(repo: str) -> dict[str, str]:
    """
    Get configurable error patterns for a specific repository.
    This replaces the hardcoded bad_codes approach with a more flexible system.
    
    Args:
        repo (str): Repository name
        
    Returns:
        dict[str, str]: Dictionary mapping error pattern names to their text patterns
    """
    # Default error patterns that apply to all repositories
    default_patterns = {
        "apply_patch_fail": APPLY_PATCH_FAIL,
        "reset_failed": RESET_FAILED,
        "tests_error": TESTS_ERROR,
        "tests_timeout": TESTS_TIMEOUT,
    }
    
    # Repository-specific error patterns can be added here
    repo_specific_patterns = {
        # Example: Add repo-specific patterns if needed
        # "redis": {
        #     "redis_specific_error": "Redis connection failed",
        # },
        # "llvm": {
        #     "llvm_build_error": "LLVM build failed",
        # },
    }
    
    # Combine default patterns with repo-specific ones
    patterns = default_patterns.copy()
    if repo in repo_specific_patterns:
        patterns.update(repo_specific_patterns[repo])
    
    return patterns


# MARK: Evaluation report functions
def get_logs_eval(test_spec: TestSpec, log_fp: str) -> tuple[dict[str, str], bool]:
    """
    Retrieve evaluation results for a task instance from its corresponding log file

    Args:
        test_spec (TestSpec): Test specification containing repo and version info
        log_fp (str): path to log file
    Returns:
        tuple[dict[str, str], bool]: (status_map, success_flag)
            - status_map: Dictionary mapping test cases to their status
            - success_flag: Whether the patch applied successfully and tests ran
    """
    # Validate inputs
    if not test_spec:
        logging.error("get_logs_eval: test_spec is None or empty")
        return {}, False
    
    if not log_fp or not os.path.exists(log_fp):
        logging.error(f"get_logs_eval: Log file does not exist: {log_fp}")
        return {}, False
    
    repo = test_spec.repo
    version = test_spec.version
    
    # Validate repo and version are in the expected mappings
    if repo not in MAP_REPO_TO_PARSER:
        logging.error(f"get_logs_eval: No parser found for repo: {repo}")
        return {}, False
    
    if repo not in MAP_REPO_VERSION_TO_SPECS or version not in MAP_REPO_VERSION_TO_SPECS[repo]:
        logging.error(f"get_logs_eval: No specs found for repo {repo}, version {version}")
        return {}, False
    
    log_parser = MAP_REPO_TO_PARSER[repo]
    test_cmd = MAP_REPO_VERSION_TO_SPECS[repo][version]["test_cmd"]
    if isinstance(test_cmd, list):
        test_cmd = test_cmd[-1]

    try:
        with open(log_fp, 'r', encoding='utf-8') as f:
            content = f.read()
    except (IOError, UnicodeDecodeError) as e:
        logging.error(f"get_logs_eval: Failed to read log file {log_fp}: {e}")
        return {}, False
    
    # Check for error patterns using configurable approach instead of hardcoded constants
    error_patterns = get_error_patterns_for_repo(repo)
    detected_errors = []
    
    for pattern_name, pattern_text in error_patterns.items():
        if pattern_text in content:
            detected_errors.append(pattern_name)
            logging.warning(f"get_logs_eval: Detected error pattern '{pattern_name}' in log file {log_fp}")
    
    if detected_errors:
        logging.error(f"get_logs_eval: Found error patterns {detected_errors} in log file {log_fp}")
        return {}, False
    
    # Validate that test output markers are present
    if not (START_TEST_OUTPUT in content and END_TEST_OUTPUT in content):
        logging.error(f"get_logs_eval: Missing test output markers in log file {log_fp}")
        return {}, False

    # Extract test output content and parse it
    try:
        content = content.split(START_TEST_OUTPUT)[1].split(END_TEST_OUTPUT)[0]
        status_map = log_parser(content, test_spec)
        logging.info(f"get_logs_eval: Successfully parsed {len(status_map)} test results from {log_fp}")
        return status_map, True
    except (IndexError, ValueError) as e:
        logging.error(f"get_logs_eval: Failed to parse test output from {log_fp}: {e}")
        return {}, False


def get_eval_tests_report(
    eval_status_map: dict[str, str],
    gold_results: dict[str, str],
    calculate_to_fail: bool = False,
    eval_type: EvalType = EvalType.PASS_AND_FAIL,
) -> dict[str, dict[str, list[str]]]:
    """
    Create a report based on failure/pass change from gold results to eval results.

    Args:
        eval_sm (dict): evaluation status map
        gold_results (dict): gold results
        calculate_to_fail (bool): whether to calculate metrics for "x to fail" tests
    Returns:
        report (dict): report of metrics

    Metric Definitions (Gold Result Pair + Eval Result):
    - Fail-Pass (F2P) + P: Success (Resolution)
    - Pass-Pass (P2P) + P: Success (Maintenance)
    - Fail-Pass (F2P) + F: Failure
    - Pass-Pass (P2P) + F: Failure

    Miscellaneous Definitions
    - Fail-Fail (F2F) + F: Failure Maintenance
    - Pass-Fail (P2F) + F: Not considered
    - Fail-Fail (F2F) + P: Success (Extra Credit)
    - Pass-Fail (P2F) + P: Not considered
    """

    def check_pass_and_fail(test_case, eval_status_map, success, failed):
        if test_passed(test_case, eval_status_map):
            # Assume silent success for now (test case not in eval_sm)
            success.append(test_case)
        elif test_failed(test_case, eval_status_map):
            failed.append(test_case)

    def check_fail_only(test_case, eval_status_map, success, failed):
        if (
            test_case in eval_status_map
            and eval_status_map[test_case] == TestStatus.FAILED.value
        ):
            failed.append(test_case)
        else:
            success.append(test_case)

    check_test_case = (
        check_pass_and_fail if eval_type == EvalType.PASS_AND_FAIL else check_fail_only
    )

    # Calculate resolution metrics
    f2p_success = []
    f2p_failure = []
    for test_case in gold_results[FAIL_TO_PASS]:
        check_test_case(test_case, eval_status_map, f2p_success, f2p_failure)

    # Calculate maintenance metrics
    p2p_success = []
    p2p_failure = []
    for test_case in gold_results[PASS_TO_PASS]:
        check_test_case(test_case, eval_status_map, p2p_success, p2p_failure)

    results = {
        FAIL_TO_PASS: {
            "success": f2p_success,
            "failure": f2p_failure,
        },
        PASS_TO_PASS: {
            "success": p2p_success,
            "failure": p2p_failure,
        },
    }

    f2f_success = []
    f2f_failure = []
    p2f_success = []
    p2f_failure = []
    if calculate_to_fail:
        # Calculate "extra credit" metrics
        for test_case in gold_results[FAIL_TO_FAIL]:
            check_test_case(test_case, eval_status_map, f2f_success, f2f_failure)

        # Calculate not considered metrics
        for test_case in gold_results[PASS_TO_FAIL]:
            check_test_case(test_case, eval_status_map, p2f_success, p2f_failure)

    results.update(
        {
            FAIL_TO_FAIL: {
                "success": f2f_success,
                "failure": f2f_failure,
            },
            PASS_TO_FAIL: {
                "success": p2f_success,
                "failure": p2f_failure,
            },
        }
    )
    return results


def compute_fail_to_pass(report: dict[str, dict[str, Any]]) -> float:
    """
    Compute fail-to-pass metric. Accepts single report as argument.
    """
    total = len(report[FAIL_TO_PASS]["success"]) + len(report[FAIL_TO_PASS]["failure"])
    if total == 0:
        return 1
    return len(report[FAIL_TO_PASS]["success"]) / total


def compute_pass_to_pass(report: dict[str, dict[str, Any]]) -> float:
    """
    Compute pass-to-pass metric. Accepts single report as argument.
    """
    total = len(report[PASS_TO_PASS]["success"]) + len(report[PASS_TO_PASS]["failure"])
    if total == 0:
        # TODO: Don't factor in p2p metrics
        return 1
    return len(report[PASS_TO_PASS]["success"]) / total


def get_resolution_status(report: dict[str, dict[str, Any]]) -> str:
    """
    Determine resolved status of an evaluation instance

    Criteria:
        - If fail-to-pass (Resolution) = 1 and pass-to-pass (Maintenance) = 1 -> FULL
        - If (fail-to-pass (Resolution) < 1 and > 0) and pass-to-pass (Maintenance) = 1 -> PARTIAL
        - Otherwise -> NO
    """
    f2p = compute_fail_to_pass(report)
    p2p = compute_pass_to_pass(report)

    if f2p == 1 and p2p == 1:
        return ResolvedStatus.FULL.value
    elif f2p < 1 and f2p > 0 and p2p == 1:
        return ResolvedStatus.PARTIAL.value
    else:
        return ResolvedStatus.NO.value


def get_eval_report(
    test_spec: TestSpec,
    prediction: dict[str, str],
    test_log_path: str,
    include_tests_status: bool,
) -> dict[str, Any]:
    """
    Generate a report of model evaluation results from a prediction, task instance,
    and evaluation log.

    Args:
        test_spec (dict): test spec containing keys "instance_id", "FAIL_TO_PASS", and "PASS_TO_PASS"
        prediction (dict): prediction containing keys "instance_id", "model_name_or_path", and "model_patch"
        log_path (str): path to evaluation log
        include_tests_status (bool): whether to include the status of each test in the returned report
    Returns:
        report (dict): report of metrics
    """
    report_map = {}

    instance_id = prediction[KEY_INSTANCE_ID]
    report_map[instance_id] = {
        "patch_is_None": False,
        "patch_exists": False,
        "patch_successfully_applied": False,
        "resolved": False,
    }

    # Check if the model patch exists
    if prediction[KEY_PREDICTION] is None:
        report_map[instance_id]["patch_is_None"] = True
        return report_map
    report_map[instance_id]["patch_exists"] = True

    # Get evaluation logs
    eval_status_map, found = get_logs_eval(test_spec, test_log_path)

    if not found:
        return report_map
    report_map[instance_id]["patch_successfully_applied"] = True

    eval_ref = {
        KEY_INSTANCE_ID: test_spec.instance_id,
        FAIL_TO_PASS: test_spec.FAIL_TO_PASS,
        PASS_TO_PASS: test_spec.PASS_TO_PASS,
    }

    eval_type = EvalType.FAIL_ONLY if test_spec.repo in FAIL_ONLY_REPOS \
        else EvalType.PASS_AND_FAIL

    report = get_eval_tests_report(
        eval_status_map, eval_ref, eval_type=eval_type
    )
    if get_resolution_status(report) == ResolvedStatus.FULL.value:
        report_map[instance_id]["resolved"] = True

    if include_tests_status:
        report_map[instance_id]["tests_status"] = report  # type: ignore

    return report_map

























