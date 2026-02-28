"""Base Agent Template for LLM-based processing with structured output."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from src.services.llm_prompt_service import LLMPrompt
from src.services.llm_service import LLMService


logger = logging.getLogger(__name__)


OutputType = TypeVar("OutputType", bound=BaseModel)


class Agent(ABC, Generic[OutputType]):
    """
    Base Agent class that handles LLM communication and structured output parsing.
    
    To create a specific agent:
    1. Subclass this agent
    2. Define the OutputType (Pydantic model) in your agent class
    3. Implement build_prompt() to create the LLMPrompt
    4. Implement parse_response() to extract the JSON from LLM response
    5. Optionally override validate_output() for custom validation
    
    Example:
        class MyAgent(Agent[MyOutputModel]):
            def build_prompt(self, **kwargs) -> LLMPrompt:
                # Build your prompt here
                return prompt
            
            def parse_response(self, response: str) -> dict:
                # Extract JSON from response
                return json_data
    """

    def __init__(self, llm_service: LLMService | None = None):
        """Initialize agent with LLM service."""
        self.llm_service = llm_service or LLMService()

    @abstractmethod
    def build_prompt(self, **kwargs) -> LLMPrompt:
        """
        Build the LLMPrompt to send to the LLM.
        
        This should be implemented by subclasses to construct
        the prompt with system messages, user messages, and images.
        
        Returns:
            LLMPrompt: Complete prompt with messages and images
        """
        pass

    @abstractmethod
    def parse_response(self, response: str) -> dict:
        """
        Parse the LLM response and extract the JSON output.
        
        This should be implemented by subclasses to extract
        structured data from the LLM's text response.
        
        Args:
            response: Raw text response from the LLM
            
        Returns:
            dict: Parsed JSON data ready for model validation
        """
        pass

    def validate_output(self, data: dict, output_model: type[OutputType]) -> OutputType:
        """
        Validate and convert parsed data to the output model.
        
        Can be overridden by subclasses for custom validation logic.
        
        Args:
            data: Parsed dictionary from parse_response()
            output_model: Target Pydantic model class
            
        Returns:
            OutputType: Validated model instance
            
        Raises:
            ValidationError: If data doesn't match the model
        """
        try:
            return output_model(**data)
        except ValidationError as e:
            logger.error("Validation error: %s", e)
            raise

    async def process(self, output_model: type[OutputType], **kwargs) -> OutputType:
        """
        Main entry point: build prompt, call LLM, parse and validate response.
        
        Args:
            output_model: Target Pydantic model for the output
            **kwargs: Arguments passed to build_prompt()
            
        Returns:
            OutputType: Validated model instance
        """
        logger.info("Building prompt for agent")
        prompt = self.build_prompt(**kwargs)

        logger.info("Calling LLM service")
        response = await self.llm_service.query(prompt)

        logger.info("Parsing response")
        parsed_data = self.parse_response(response)

        logger.info("Validating output")
        output = self.validate_output(parsed_data, output_model)

        return output


class JsonAgent(Agent[OutputType]):
    """
    Specialized Agent for LLMs that output JSON in Markdown code blocks.
    
    Automatically handles extraction of JSON from markdown blocks.
    Subclasses only need to implement build_prompt().
    """

    def parse_response(self, response: str) -> dict:
        """
        Extract JSON from markdown code block.
        
        Expected format:
            ```json
            { "key": "value" }
            ```
        """
        # Try to find JSON in markdown block
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            if end > start:
                json_str = response[start:end].strip()
                logger.debug("Extracted JSON from markdown block")
                return json.loads(json_str)
        
        # Try to parse entire response as JSON
        try:
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse response as JSON: %s", e)
            raise ValueError(f"Could not extract JSON from response: {response[:200]}...")
