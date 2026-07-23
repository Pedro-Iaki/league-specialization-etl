from typing import Protocol, Any

class APIClient(Protocol):
	def get_patch(self) -> str:
		...

	def get(self, url: str, **kwargs) -> Any:
		...