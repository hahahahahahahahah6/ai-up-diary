# 运营日志 (Operations log)

Every run of `diary.py` appends an entry here: the day, the mode used,
and the episode's opening line. This file plus `state.json` is the host's
long-term memory — the script generator reads it before writing the next
episode, so promises and running gags survive between runs.
