from utils.instructions_concatenator import generate_instruction


def test_instruction_carries_trimmed_role_goal_backstory_and_the_guidelines():
    result = generate_instruction(role="  Support Agent  ", goal="  resolve tickets ", backstory=" experienced helper ")

    for part in ("Support Agent", "resolve tickets", "experienced helper", "Be clear and concise"):
        assert part in result
    assert "  Support Agent  " not in result
