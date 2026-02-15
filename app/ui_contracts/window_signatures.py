"""Window and control signatures for stable UI Automation selectors."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class ControlSelector:
    control_type: Optional[str] = None
    automation_id: Optional[str] = None
    class_name_regex: Optional[str] = None
    title_regex: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "control_type": self.control_type,
            "automation_id": self.automation_id,
            "class_name_regex": self.class_name_regex,
            "title_regex": self.title_regex,
        }


@dataclass(frozen=True)
class WindowSignature:
    signature_id: str
    process_names: Sequence[str]
    class_name_regex: Optional[str] = None
    title_regex: Optional[str] = None
    control_type: str = "Window"
    required_controls: Sequence[ControlSelector] = field(default_factory=tuple)
    notes: str = ""

    def matches_info(self, info: Dict[str, Any]) -> bool:
        process_name = str(info.get("process_name", "")).lower()
        class_name = str(info.get("class_name", ""))
        title = str(info.get("title", ""))
        control_type = str(info.get("control_type", ""))

        if self.process_names:
            accepted = {value.lower() for value in self.process_names}
            if process_name not in accepted:
                return False
        if self.control_type and control_type and self.control_type != control_type:
            return False
        if self.class_name_regex and not re.search(self.class_name_regex, class_name, re.IGNORECASE):
            return False
        if self.title_regex and not re.search(self.title_regex, title, re.IGNORECASE):
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signature_id": self.signature_id,
            "process_names": list(self.process_names),
            "class_name_regex": self.class_name_regex,
            "title_regex": self.title_regex,
            "control_type": self.control_type,
            "required_controls": [selector.to_dict() for selector in self.required_controls],
            "notes": self.notes,
        }


AKABAK_MAIN_WINDOW = WindowSignature(
    signature_id="akabak_main_window",
    process_names=("akabak.exe",),
    class_name_regex=r"(TForm_Main|Qt|QWidget|AKABAK|MainWindow)",
    title_regex=r"(Akabak|AKABAK)",
    required_controls=(
        ControlSelector(control_type="MenuBar"),
    ),
    notes="Main AKABAK shell window. Title regex is not the sole discriminator.",
)

AKABAK_IMPORT_DIALOG = WindowSignature(
    signature_id="akabak_import_dialog",
    process_names=("akabak.exe",),
    class_name_regex=r"(#32770|Dialog)",
    title_regex=r"(Import|Open|ABEC)",
    required_controls=(
        ControlSelector(control_type="Edit"),
        ControlSelector(control_type="Button"),
    ),
    notes="File/import dialog used for ABEC project loading.",
)

AKABAK_INTERPRETER_WINDOW = WindowSignature(
    signature_id="akabak_interpreter_window",
    process_names=("akabak.exe",),
    class_name_regex=r"(TForm_Interpreter)",
    title_regex=r"(Importing Scripts|ABEC Projects)",
    required_controls=(
        ControlSelector(class_name_regex=r"TRzMenuButton", title_regex=r"(Open ABEC Project)"),
        ControlSelector(class_name_regex=r"TRzBitBtn", title_regex=r"(Start Importing)"),
    ),
    notes="ABEC interpreter window shown after Tools -> Import ABEC project command.",
)

AKABAK_OPEN_FILE_DIALOG = WindowSignature(
    signature_id="akabak_open_file_dialog",
    process_names=("akabak.exe",),
    class_name_regex=r"(#32770)",
    title_regex=r"(Open|Opening|Oeffnen|Öffnen)",
    required_controls=(
        ControlSelector(control_type="Edit", automation_id="1148"),
        ControlSelector(control_type="Button", automation_id="1"),
    ),
    notes="Windows common open-file dialog used by the ABEC interpreter.",
)

AKABAK_SOLVE_PROGRESS = WindowSignature(
    signature_id="akabak_solve_progress",
    process_names=("akabak.exe",),
    class_name_regex=r"(#32770|Dialog|Qt|TForm_.*)",
    title_regex=r"(Solve|Calculation|Progress|Running)",
    required_controls=(ControlSelector(control_type="ProgressBar"),),
    notes="Solve/progress window shown while AKABAK runs the simulation.",
)

VACS_MAIN_WINDOW = WindowSignature(
    signature_id="vacs_main_window",
    process_names=("vacsviewer_32.exe", "vacsviewer.exe"),
    class_name_regex=r"(TForm_DatMain|Qt|QWidget|VACS|MainWindow)",
    title_regex=r"(VacsViewer|VACS|Viewer)",
    required_controls=(
        ControlSelector(control_type="MenuBar"),
    ),
    notes="Main VACS viewer window.",
)

VACS_EXPORT_DIALOG = WindowSignature(
    signature_id="vacs_export_dialog",
    process_names=("vacsviewer_32.exe", "vacsviewer.exe"),
    class_name_regex=r"(#32770|Dialog|TForm_Export|TForm_Edit|TForm_Picture)",
    title_regex=r"(Export|Save|ASCII|TXT)",
    required_controls=(
        ControlSelector(control_type="Edit"),
        ControlSelector(control_type="Button"),
    ),
    notes="Dialog used for TXT export destinations/settings.",
)

COMMON_FILE_DIALOG = WindowSignature(
    signature_id="common_file_dialog",
    process_names=("akabak.exe", "vacsviewer_32.exe", "vacsviewer.exe"),
    class_name_regex=r"(#32770|Dialog)",
    title_regex=r"(Open|Save|Import|Export)",
    required_controls=(
        ControlSelector(control_type="Edit"),
        ControlSelector(control_type="Button"),
    ),
    notes="Windows common file dialog signature used across tools.",
)


WINDOW_SIGNATURES: Dict[str, WindowSignature] = {
    AKABAK_MAIN_WINDOW.signature_id: AKABAK_MAIN_WINDOW,
    AKABAK_IMPORT_DIALOG.signature_id: AKABAK_IMPORT_DIALOG,
    AKABAK_INTERPRETER_WINDOW.signature_id: AKABAK_INTERPRETER_WINDOW,
    AKABAK_OPEN_FILE_DIALOG.signature_id: AKABAK_OPEN_FILE_DIALOG,
    AKABAK_SOLVE_PROGRESS.signature_id: AKABAK_SOLVE_PROGRESS,
    VACS_MAIN_WINDOW.signature_id: VACS_MAIN_WINDOW,
    VACS_EXPORT_DIALOG.signature_id: VACS_EXPORT_DIALOG,
    COMMON_FILE_DIALOG.signature_id: COMMON_FILE_DIALOG,
}


def signatures_for_process(process_name: str) -> List[WindowSignature]:
    key = str(process_name).lower()
    return [
        signature
        for signature in WINDOW_SIGNATURES.values()
        if not signature.process_names or key in {value.lower() for value in signature.process_names}
    ]


def signature_as_jsonable(signature_id: str) -> Dict[str, Any]:
    signature = WINDOW_SIGNATURES.get(signature_id)
    if signature is None:
        raise KeyError(f"Unknown signature: {signature_id}")
    return signature.to_dict()


def all_signature_dicts() -> List[Dict[str, Any]]:
    return [signature.to_dict() for signature in WINDOW_SIGNATURES.values()]
