# Future Enhancements

Planned enhancements that are out of scope for the current phased implementation plan but
worth preserving. These are not committed to a specific phase yet.

* Modify Chat History: Delete/modify messages in the chat history.
* Multiple Conversations: Persist more than the current conversation and allow switching between them.
* CI Pipeline: Once the repo has a remote (e.g. GitHub), add a CI workflow that runs
  `poetry run ruff check .` and `poetry run pytest` on every push/PR so verification no longer
  depends on local discipline alone.
