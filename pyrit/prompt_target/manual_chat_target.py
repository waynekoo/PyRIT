# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging


import tkinter as tk
from tkinter import ttk

from httpx import HTTPStatusError
from typing import Optional

from pyrit.chat_message_normalizer import ChatMessageNop, ChatMessageNormalizer
from pyrit.common import default_values, net_utility
from pyrit.exceptions import EmptyResponseException, RateLimitException
from pyrit.exceptions import handle_bad_request_exception, pyrit_target_retry
from pyrit.memory import MemoryInterface
from pyrit.models import ChatMessage, PromptRequestResponse
from pyrit.models import construct_response_from_request
from pyrit.prompt_target import PromptChatTarget, limit_requests_per_minute

import asyncio
import threading
from functools import partial

logger = logging.getLogger(__name__)


class ManualChatTarget(PromptChatTarget):


    def __init__(
        self,
        *,
        chat_message_normalizer: ChatMessageNormalizer = ChatMessageNop(),
        memory: MemoryInterface = None,
        max_tokens: int = 400,
        temperature: float = 1.0,
        top_p: float = 1.0,
        repetition_penalty: float = 1.2,
        max_requests_per_minute: Optional[int] = None,
    ) -> None:
        """
        Initializes an instance of the AzureMLChatTarget class.

        Args:
            endpoint_uri (str, optional): The URI of the Azure ML endpoint.
                Defaults to None.
            api_key (str, optional): The API key for accessing the Azure ML endpoint.
                Defaults to None.
            chat_message_normalizer (ChatMessageNormalizer, optional): The chat message normalizer.
                Defaults to ChatMessageNop().
            memory (MemoryInterface, optional): The memory interface.
                Defaults to None.
            max_tokens (int, optional): The maximum number of tokens to generate in the response.
                Defaults to 400.
            temperature (float, optional): The temperature for generating diverse responses.
                Defaults to 1.0.
            top_p (float, optional): The top-p value for generating diverse responses.
                Defaults to 1.0.
            repetition_penalty (float, optional): The repetition penalty for generating diverse responses.
                Defaults to 1.2.
            max_requests_per_minute (int, optional): Number of requests the target can handle per
                minute before hitting a rate limit. The number of requests sent to the target
                will be capped at the value provided.
        """
        PromptChatTarget.__init__(self, memory=memory, max_requests_per_minute=max_requests_per_minute)
        self.chat_message_normalizer = chat_message_normalizer

    @limit_requests_per_minute
    async def send_prompt_async(self, *, prompt_request: PromptRequestResponse) -> PromptRequestResponse:

        self._validate_request(prompt_request=prompt_request)
        request = prompt_request.request_pieces[0]

        messages = self._memory.get_chat_messages_with_conversation_id(conversation_id=request.conversation_id)

        messages.append(request.to_chat_message())

        logger.info(f"Sending the following prompt to the prompt target: {request}")

 
        resp_text = await self.async_gui_input(request.converted_value)
        if not resp_text:
            raise EmptyResponseException(message="The chat returned an empty response.")

        response_entry = construct_response_from_request(request=request, response_text_pieces=[resp_text])


        logger.info(
            "Received the following response from the prompt target"
            + f"{response_entry.request_pieces[0].converted_value}"
        )
        return response_entry


    def gui_input(self, prompt):  # Added self parameter
        # Create and manage the GUI window
        window = tk.Tk()
        window.title("Chat Input")  # Changed title to be more descriptive
        
        user_input = tk.StringVar()
        result = []
        
        # Make prompt display larger and scrollable for longer prompts
        prompt_frame = ttk.Frame(window)
        prompt_frame.pack(fill='both', expand=True, padx=20, pady=10)
        
        prompt_text = tk.Text(prompt_frame, height=5, wrap='word')
        prompt_text.insert('1.0', prompt)
        prompt_text.config(state='disabled')  # Make it readonly
        prompt_text.pack(fill='both', expand=True)
        
        input_entry = ttk.Entry(window, textvariable=user_input)
        input_entry.pack(padx=20, pady=5, fill='x')
        input_entry.focus()
        
        def on_submit():
            result.append(user_input.get())
            window.destroy()
        
        submit_btn = ttk.Button(window, text="Submit", command=on_submit)
        submit_btn.pack(pady=10)
        
        window.bind('<Return>', lambda e: on_submit())
        
        # Set a reasonable minimum size
        window.minsize(400, 300)
        window.eval('tk::PlaceWindow . center')
        
        window.mainloop()
        return result[0] if result else None

    async def async_gui_input(self, prompt):  # Added self parameter
        # Run the GUI input in a thread pool to not block the event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self.gui_input, prompt))

   
    def _validate_request(self, *, prompt_request: PromptRequestResponse) -> None:
        if len(prompt_request.request_pieces) != 1:
            raise ValueError("This target only supports a single prompt request piece.")

        if prompt_request.request_pieces[0].converted_value_data_type != "text":
            raise ValueError("This target only supports text prompt input.")
