from agent.llm import ExtractionResponse, StructuredLLM


def extract_with_llm(page_text: str, metric: str, llm: StructuredLLM | None = None) -> ExtractionResponse:
    wrapper = llm or StructuredLLM()
    return wrapper.call(f"Extract {metric} from this page text:\n{page_text}", ExtractionResponse)
