# VACS Export Setter Probe Report

- Generated at: `2026-02-21T14:25:54.800919+00:00`
- Dialog found: `True`
- Process ID: `11740`
- Dialog signature: `{"handle": 4196276, "title": "Data Export", "class_name": "TForm_Export", "control_type": "Window", "automation_id": "", "process_id": 11740}`

## Control Settable Classification

| ControlPurpose | Found | BeforeState | Settable | Reason |
|---|---|---|---|---|
| IncludeHeader | yes | CHECKED | NON-SETTABLE | no_method_changed_state |
| AbscissaDataBlocks | yes | UNCHECKED | NON-SETTABLE | no_method_changed_state |
| TryMatrixForm | yes | UNCHECKED | NON-SETTABLE | no_method_changed_state |
| SingleFile | yes | UNCHECKED | NON-SETTABLE | no_method_changed_state |
| ComplexFormat | yes | UNCHECKED | NON-SETTABLE | no_method_changed_state |

## Matched Controls

| ControlPurpose | Handle | ClassName | ControlType | AutomationId | CtrlId | CheckboxIndex | Win32Index | Title/Text |
|---|---|---|---|---|---|---|---|---|
| IncludeHeader | 1050536 | TRzCheckBox | Pane | 1050536 | 1050536 | 3 | 6 | Export of parameters / Export of parameters |
| AbscissaDataBlocks | 2033636 | TRzCheckBox | Pane | 2033636 | 2033636 | 5 | 11 | Abscissa separat / Abscissa separat |
| TryMatrixForm | 788450 | TRzCheckBox |  |  | 788450 | 0 | 12 | Try matrix form |
| SingleFile | 1574358 | TRzCheckBox |  |  | 1574358 | 7 | 3 | Single file |
| ComplexFormat | 788396 | TRzCheckBox | Pane | 788396 | 788396 | 8 | 7 | Phase as radiant / Phase as radiant |

## Method Attempt Table

| ControlPurpose | SelectorUsed | MethodAttempted | BeforeState | AfterState | Success |
|---|---|---|---|---|---|
| IncludeHeader | automation_id=1050536,ctrl_id=1050536,class=TRzCheckBox,name~(export.*parameters|parameter.*export|parameter.*ausgabe),checkbox_index=3,win32_index=6 | bm_setcheck | CHECKED | CHECKED | false |
| IncludeHeader | automation_id=1050536,ctrl_id=1050536,class=TRzCheckBox,name~(export.*parameters|parameter.*export|parameter.*ausgabe),checkbox_index=3,win32_index=6 | bm_click | CHECKED | CHECKED | false |
| IncludeHeader | automation_id=1050536,ctrl_id=1050536,class=TRzCheckBox,name~(export.*parameters|parameter.*export|parameter.*ausgabe),checkbox_index=3,win32_index=6 | uia_toggle | CHECKED | ERROR | false |
| IncludeHeader | automation_id=1050536,ctrl_id=1050536,class=TRzCheckBox,name~(export.*parameters|parameter.*export|parameter.*ausgabe),checkbox_index=3,win32_index=6 | uia_invoke | CHECKED | ERROR | false |
| AbscissaDataBlocks | automation_id=2033636,ctrl_id=2033636,class=TRzCheckBox,name~(abscissa|abzisse|abscissa separat),checkbox_index=5,win32_index=11 | bm_setcheck | UNCHECKED | UNCHECKED | false |
| AbscissaDataBlocks | automation_id=2033636,ctrl_id=2033636,class=TRzCheckBox,name~(abscissa|abzisse|abscissa separat),checkbox_index=5,win32_index=11 | bm_click | UNCHECKED | UNCHECKED | false |
| AbscissaDataBlocks | automation_id=2033636,ctrl_id=2033636,class=TRzCheckBox,name~(abscissa|abzisse|abscissa separat),checkbox_index=5,win32_index=11 | uia_toggle | UNCHECKED | ERROR | false |
| AbscissaDataBlocks | automation_id=2033636,ctrl_id=2033636,class=TRzCheckBox,name~(abscissa|abzisse|abscissa separat),checkbox_index=5,win32_index=11 | uia_invoke | UNCHECKED | ERROR | false |
| TryMatrixForm | class=TRzCheckBox,name~(try\s*matrix\s*form|matrix\s*form),checkbox_index=0,win32_index=12 | bm_setcheck | UNCHECKED | UNCHECKED | false |
| TryMatrixForm | class=TRzCheckBox,name~(try\s*matrix\s*form|matrix\s*form),checkbox_index=0,win32_index=12 | bm_click | UNCHECKED | UNCHECKED | false |
| TryMatrixForm | class=TRzCheckBox,name~(try\s*matrix\s*form|matrix\s*form),checkbox_index=0,win32_index=12 | uia_toggle | UNCHECKED | UNCHECKED | false |
| TryMatrixForm | class=TRzCheckBox,name~(try\s*matrix\s*form|matrix\s*form),checkbox_index=0,win32_index=12 | uia_invoke | UNCHECKED | UNCHECKED | false |
| SingleFile | class=TRzCheckBox,name~(single file|single),checkbox_index=7,win32_index=3 | bm_setcheck | UNCHECKED | UNCHECKED | false |
| SingleFile | class=TRzCheckBox,name~(single file|single),checkbox_index=7,win32_index=3 | bm_click | UNCHECKED | UNCHECKED | false |
| SingleFile | class=TRzCheckBox,name~(single file|single),checkbox_index=7,win32_index=3 | uia_toggle | UNCHECKED | UNCHECKED | false |
| SingleFile | class=TRzCheckBox,name~(single file|single),checkbox_index=7,win32_index=3 | uia_invoke | UNCHECKED | UNCHECKED | false |
| ComplexFormat | automation_id=788396,ctrl_id=788396,class=TRzCheckBox,name~(phase\s*as\s*radiant|phase.*radian),checkbox_index=8,win32_index=7 | bm_setcheck | UNCHECKED | UNCHECKED | false |
| ComplexFormat | automation_id=788396,ctrl_id=788396,class=TRzCheckBox,name~(phase\s*as\s*radiant|phase.*radian),checkbox_index=8,win32_index=7 | bm_click | UNCHECKED | UNCHECKED | false |
| ComplexFormat | automation_id=788396,ctrl_id=788396,class=TRzCheckBox,name~(phase\s*as\s*radiant|phase.*radian),checkbox_index=8,win32_index=7 | uia_toggle | UNCHECKED | ERROR | false |
| ComplexFormat | automation_id=788396,ctrl_id=788396,class=TRzCheckBox,name~(phase\s*as\s*radiant|phase.*radian),checkbox_index=8,win32_index=7 | uia_invoke | UNCHECKED | ERROR | false |
