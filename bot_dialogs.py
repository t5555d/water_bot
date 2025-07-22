import asyncio
import logging
import re
import telethon as tt

from dataclasses import dataclass


logger = logging.getLogger(__name__)

SEND_DELAY = 1.0


@dataclass
class Account:
    id: str
    api_id: int
    api_hash: str
    phone: str = None
    password: str = None

    def __repr__(self):
        return f"Account {self.id}"


class Session:
    def __init__(self, account: Account):
        self.account = account
        self.client = tt.TelegramClient(
            self.account.id,
            self.account.api_id,
            self.account.api_hash,
            sequential_updates=True,
        )

    async def start(self):
        await self.client.start(
            phone=self.account.phone,
            password=self.account.password,
        )

    async def stop(self):
        await self.client.disconnect()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()

    def dialog(self, bot_name):
        return BotDialog(self, bot_name)


class Button:
    def __init__(self, message, text):
        self.message = message
        self.text = text

    def __repr__(self):
        return f"Button({self.text})"

    def matches(self, pattern):
        return re.match(pattern, self.text)

    async def click(self):
        await asyncio.sleep(SEND_DELAY)
        logger.info("-> %s", self.text)
        await self.message.click(text=self.text)


@dataclass
class WaitResult:
    message: str
    matches: tuple = None
    buttons: list[Button] = None


class BotDialog:
    def __init__(self, session: Session, bot_name: str):
        self.session = session
        self.client = session.client
        self.bot_name = bot_name
        self.message_queue = asyncio.Queue()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()

    async def start(self):
        self.bot_id = await self.client.get_entity(self.bot_name)
        self.client.add_event_handler(self._on_message, tt.events.NewMessage(from_users=[self.bot_id], incoming=True))
        self.client.add_event_handler(self._on_message, tt.events.MessageEdited(from_users=[self.bot_id], incoming=True))

    async def stop(self):
        self.client.remove_event_handler(self._on_message)

    async def _on_message(self, event):
        logger.debug("Message: %s", event.message)
        logger.info("<- %s", event.message.message)
        self.message_queue.put_nowait(event.message)

    async def send(self, message: str):
        await asyncio.sleep(SEND_DELAY)
        logger.info("-> %s", message)
        await self.client.send_message(self.bot_id, message)

    async def wait(self) -> WaitResult:
        next = await self.message_queue.get()
        result = WaitResult(
            message=next.message,
            buttons=[],
        )
        if next.reply_markup:
            result.buttons = [
                Button(next, btn.text)
                for row in next.reply_markup.rows
                for btn in row.buttons
            ]

        return result

    async def expect(self, expected_message: str, answer: str = None) -> WaitResult:
        return await self.expects({ expected_message : answer })

    async def expects(self, expected_messages: dict[str,str]) -> WaitResult:
        result = await self.wait()
        for expected_message, answer in expected_messages.items():
            if match := re.match(expected_message, result.message):
                result.matches = match.groups()
                break
        else:
            expected = '\n'.join(msg for msg in expected_messages)
            raise RuntimeError(f"Got unexpected message '{message}', expected:\n{expected}")

        if answer:
            for button in result.buttons:
                if button.matches(answer):
                    await button.click()
                    break
            else:
                raise RuntimeError(f"Expected answer '{answer}' was not suggested: {result.buttons}")

        return result

    async def match(self, expected_message) -> tuple:
        result = await self.expect(expected_message)
        return result.matches

    async def seek(self, answer, *fallback_options, max_iterations=10):
        for i in range(max_iterations):
            result = await self.wait()
            buttons = result.buttons

            if not buttons:
                continue

            for button in buttons:
                if button.matches(answer):
                    await button.click()
                    return

            for button in buttons:
                if button.text in fallback_options:
                    await button.click()
                    break
            else:
                logger.error("Failed to choose from options: %s", buttons)
                logger.error("Expected one of: %s", fallback_options)
                raise RuntimeError("Failed to choose from options")
        raise RuntimeError(f"Failed to seek expected answer in {max_iterations} iterations")
