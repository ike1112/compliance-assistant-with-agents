import os
from crewai import Agent, Crew, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.tasks.conditional_task import ConditionalTask
from crewai_tools.aws.bedrock.agents.invoke_agent_tool import BedrockInvokeAgentTool

# Sets up three agents and runs them in order.
# Only the first (the researcher) can look things up in the
# compliance documents (a vector database).
# The other two only use what it found.


def _has_grounded_findings(previous_output) -> bool:
	# True only if the previous stage produced real grounded content.
	# When the knowledge base has no source, the researcher returns
	# just "Not found in knowledge base". If so, the writer and the
	# designer must not run, so they cannot turn an empty handoff
	# into a confident report from their own memory.
	text = (getattr(previous_output, "raw", "") or "").strip()
	if not text:
		return False
	if len(text) < 200 and text.lower().startswith("not found in knowledge base"):
		return False
	return True


@CrewBase
class ComplianceAssistant():
	"""ComplianceAssistant crew"""

	agents_config = 'config/agents.yaml'
	tasks_config = 'config/tasks.yaml'

	# No agent below sets a model. CrewAI falls back to the MODEL
	# env var from .env (bedrock/us.amazon.nova-pro-v1:0), so all
	# three share the same one. Change it there to change all three.

	# Looks things up in the compliance documents by asking a
	# separate AI that has already read them.
	agent_tool = BedrockInvokeAgentTool(
    	agent_id=os.environ.get('AGENT_ID'),
    	agent_alias_id=os.environ.get('AGENT_ALIAS_ID')
	)

	# Looks up the rules and pulls out the key points.
	# The only agent with the lookup tool.
	@agent
	def regulation_researcher(self) -> Agent:
		return Agent(
			config=self.agents_config['regulation_researcher'],
			tools=[self.agent_tool],
			# Can pass part of its work to another agent.
			allow_delegation=True,
			verbose=True
		)

	# Turns the researcher's key points into a full written report.
	@agent
	def report_writer(self) -> Agent:
		return Agent(
			config=self.agents_config['report_writer'],
			verbose=True
		)

	# Works out how to build the report's requirements on AWS.
	@agent
	def solution_designer(self) -> Agent:
		return Agent(
			config=self.agents_config['solution_designer'],
			verbose=True
		)

	# Each task writes its own output so every stage can be checked.
	# Files land in output/, numbered in run order.
	@task
	def compliance_analysis_task(self) -> Task:
		return Task(
			config=self.tasks_config['compliance_analysis_task'],
			output_file='output/1-requirements.md'
		)

	# Skipped if the research stage found no grounded source, so the
	# writer cannot turn an empty handoff into a report from memory.
	@task
	def compliance_reporting_task(self) -> ConditionalTask:
		return ConditionalTask(
			condition=_has_grounded_findings,
			config=self.tasks_config['compliance_reporting_task'],
			output_file='output/2-report.md'
		)

	# Skipped too if the report stage was skipped (its output is then
	# empty, which fails the same check).
	@task
	def compliance_solution_task(self) -> ConditionalTask:
		return ConditionalTask(
			condition=_has_grounded_findings,
			config=self.tasks_config['compliance_solution_task'],
			output_file='output/3-solution.md'
		)

	# Runs the three agents in order, passing each one's output
	# to the next.
	@crew
	def crew(self) -> Crew:
		"""Creates the Compliance Automation crew"""

		return Crew(
			# self.agents and self.tasks are filled in automatically by
			# @CrewBase: it collects every @agent and @task method above,
			# in the order they are defined.
			agents=self.agents,
			tasks=self.tasks,
			# Prints each agent's steps and output while running.
			# Set False for a silent run; output is unchanged.
			verbose=True,
			max_rpm=10,
		)
