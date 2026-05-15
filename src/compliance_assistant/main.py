#!/usr/bin/env python
import os
import sys
import warnings
from datetime import datetime
from compliance_assistant.crew import ComplianceAssistant

# Hides a noisy warning from the pysbd library. Does not affect results.
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# This file holds the entry points for the local CLI. Each function
# below backs one command (wired up in pyproject.toml [project.scripts]):
#   run / run_crew -> run()     the normal path
#   train          -> train()
#   replay         -> replay()
#   test           -> test()

# The subject to analyze. Comes from TOPIC in .env and is required by
# run, train, and test. It fills the {topic} placeholder in the agent
# and task prompts.
topic = os.environ.get('TOPIC')
if topic is None:
    raise Exception("TOPIC is not defined. Please add the topic as an argument")

def run():
    """Run the three agents once and write report.md. This is `crewai run`."""
    # topic and current_year fill the {topic} and {current_year}
    # placeholders in the agent and task prompts.
    inputs = {
        'topic': topic,
        'current_year': str(datetime.now().year)
    }
    
    try:
        ComplianceAssistant().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """Run the crew repeatedly to refine it. Args: iteration count, output filename."""
    # Only topic is passed here, so prompts that use {current_year}
    # will not fill in under train.
    inputs = {
        "topic": topic
    }
    try:
        ComplianceAssistant().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """Re-run from a previously saved task. Arg: the task id to replay from."""
    try:
        ComplianceAssistant().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """Run the crew several times and score the output. Args: iteration count, model name."""
    inputs = {
        "topic": topic,
        "current_year": str(datetime.now().year)
    }
    try:
        ComplianceAssistant().crew().test(n_iterations=int(sys.argv[1]), openai_model_name=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")
