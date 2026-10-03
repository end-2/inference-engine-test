"""Prompt fallback for checkpoints without a chat template."""


class PlainTextPrompts:
    def prepare_prompt(self, messages):
        if self.tokenizer.chat_template:
            return super().prepare_prompt(messages)
        # The base checkpoint has no chat template. A single user message is raw text.
        if len(messages) == 1 and messages[0]["role"] == "user":
            text = messages[0]["content"]
        else:
            text = "\n".join(f"{message['role'].capitalize()}: {message['content']}"
                             for message in messages) + "\nAssistant:"
        with self.tokenizer_lock:
            return self.tokenizer.encode(text, add_special_tokens=False)
