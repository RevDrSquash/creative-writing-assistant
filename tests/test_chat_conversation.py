"""Unit tests for chat conversation history management."""

from langchain_core.messages import AIMessage, HumanMessage

from app.persistence import ChatConversation, StoredChatMessage


class InMemoryChatMessageStore:
    def __init__(self) -> None:
        self.messages: list[StoredChatMessage] = []

    def load(self) -> list[StoredChatMessage]:
        return list(self.messages)

    def append(self, message: StoredChatMessage) -> None:
        self.messages.append(message)

    def clear(self) -> None:
        self.messages.clear()


def test_add_user_message_then_history_returns_appended_turn() -> None:
    conversation = ChatConversation(store=InMemoryChatMessageStore())

    message = conversation.add_user_message("Draft a quiet opening scene.")

    assert message == {"role": "user", "content": "Draft a quiet opening scene."}
    assert conversation.history() == [message]


def test_add_assistant_message_then_agent_messages_returns_langchain_history() -> None:
    conversation = ChatConversation(store=InMemoryChatMessageStore())
    conversation.add_user_message("Draft a quiet opening scene.")
    conversation.add_assistant_message("The room held its breath.")

    messages = conversation.agent_messages()

    assert len(messages) == 2
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == "Draft a quiet opening scene."
    assert isinstance(messages[1], AIMessage)
    assert messages[1].content == "The room held its breath."


def test_clear_empties_history_and_agent_messages() -> None:
    conversation = ChatConversation(store=InMemoryChatMessageStore())
    conversation.add_user_message("Hello")
    conversation.add_assistant_message("Hi there")

    conversation.clear()

    assert conversation.history() == []
    assert conversation.agent_messages() == []


def test_chat_conversation_uses_injected_store() -> None:
    store = InMemoryChatMessageStore()
    conversation = ChatConversation(store=store)

    conversation.add_user_message("Use this store.")

    assert store.messages == [{"role": "user", "content": "Use this store."}]
