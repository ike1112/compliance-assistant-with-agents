#!/usr/bin/env python
import os
import sys
import warnings
from datetime import datetime
from compliance_assistant.crew import ComplianceAssistant
from compliance_assistant.startup import validate_startup_config

# Hides a noisy warning from the pysbd library. Does not affect results.
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This file holds the entry points for the local CLI. Each function
# below backs one command (wired up in pyproject.toml [project.scripts]):
#   run / run_crew -> run()     the normal path
#   train          -> train()
#   replay         -> replay()
#   test           -> test()
#
# Each entry point validates config first (validate_startup_config):
# missing/blank/placeholder TOPIC, MODEL, or agent ids fail fast here
# with one clear error, before any model spend. It is called per
# command, not at import, so importing this module has no side effects.

def run():
    """Run the three agents once. This is `crewai run`. Output goes to output/."""
    validate_startup_config(os.environ)
    # topic (TOPIC from .env, validated above) and current_year fill the
    # {topic} and {current_year} placeholders in the agent/task prompts.
    inputs = {
        'topic': os.environ['TOPIC'],
        'current_year': str(datetime.now().year)
    }

    try:
        ComplianceAssistant().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """Run the crew repeatedly to refine it. Args: iteration count, output filename."""
    validate_startup_config(os.environ)
    # Only topic is passed here, so prompts that use {current_year}
    # will not fill in under train.
    inputs = {
        "topic": os.environ['TOPIC']
    }
    try:
        ComplianceAssistant().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """Re-run from a previously saved task. Arg: the task id to replay from."""
    validate_startup_config(os.environ)
    try:
        ComplianceAssistant().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """Run the crew several times and score the output. Args: iteration count, model name."""
    validate_startup_config(os.environ)
    inputs = {
        "topic": os.environ['TOPIC'],
        "current_year": str(datetime.now().year)
    }
    try:
        ComplianceAssistant().crew().test(n_iterations=int(sys.argv[1]), openai_model_name=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")
