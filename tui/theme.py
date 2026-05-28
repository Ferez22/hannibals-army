"""Textual CSS theme — uses config.PALETTE colors."""

CSS = """
Screen {
    background: #0D1117;
    color: #FFFFFF;
}

Header {
    background: #0D1117;
    color: #5BC8F5;
    text-style: bold;
}

Footer {
    background: #0D1117;
    color: #4A5568;
}

#status-bar {
    height: 1;
    background: #0D1117;
    color: #5BC8F5;
    padding: 0 1;
}
#status-bar.paused {
    color: #E74C3C;
    text-style: bold;
}

.section-title {
    color: #F5A623;
    text-style: bold;
    margin: 1 0 0 1;
}

.dim {
    color: #4A5568;
}

.success { color: #2ECC71; }
.danger  { color: #E74C3C; }
.warn    { color: #F5D020; }
.hi      { color: #F5A623; }

Input {
    background: #161B22;
    color: #FFFFFF;
    border: tall #4A5568;
}
Input:focus {
    border: tall #5BC8F5;
}

Button {
    background: #161B22;
    color: #FFFFFF;
    border: tall #4A5568;
}
Button:hover {
    background: #1F2937;
    border: tall #F5A623;
}
Button.-primary {
    background: #5BC8F5;
    color: #0D1117;
    text-style: bold;
}
Button.-danger {
    background: #E74C3C;
    color: #FFFFFF;
}
Button.-success {
    background: #2ECC71;
    color: #0D1117;
}

DataTable {
    background: #0D1117;
    color: #FFFFFF;
}
DataTable > .datatable--header {
    background: #161B22;
    color: #F5A623;
    text-style: bold;
}
DataTable > .datatable--cursor {
    background: #1F2937;
}

ListView {
    background: #0D1117;
    color: #FFFFFF;
    border: tall #4A5568;
}
ListView > ListItem {
    padding: 0 1;
}
ListView > ListItem.--highlight {
    background: #1F2937;
}

RichLog {
    background: #0D1117;
    color: #FFFFFF;
    border: tall #4A5568;
}

#nav {
    height: 3;
    background: #161B22;
    color: #FFFFFF;
}
#nav Button {
    width: 14;
    margin: 0 1;
}

/* Browser + Pending + Review split: table on left (50%), detail on right (50%) */
#b-table, #p-table, #r-table {
    width: 50%;
    height: 1fr;
}
#b-detail, #p-detail, #r-detail {
    width: 50%;
    height: 1fr;
    border: tall #4A5568;
    padding: 0 1;
}
#p-actions, #r-actions, #b-actions {
    height: 3;
    align-horizontal: left;
    width: 50%;
    margin: 0;
    padding: 0;
}
#p-actions Button, #r-actions Button, #b-actions Button {
    min-width: 10;
    width: auto;
    height: 3;
    margin: 0 1 0 0;
    padding: 0 1;
}

/* Ingest input row layout */
Horizontal {
    height: auto;
}

/* Attach screen */
#a-table {
    width: 50%;
    height: 1fr;
}
#a-form {
    width: 50%;
    padding: 1 2;
}
#a-form Input {
    margin: 1 0;
}
#a-form Button {
    width: 14;
}

/* Edges form */
#ed-form {
    padding: 1 2;
    height: auto;
}
.ed-row {
    height: auto;
    margin: 0 0 1 0;
}
.ed-label {
    width: 8;
    color: #F5A623;
    text-style: bold;
    content-align-vertical: middle;
}
#ed-form Select, #ed-form Input {
    width: 1fr;
}
#ed-form Button {
    width: 16;
    margin-left: 8;
}
#ed-existing {
    border: tall #4A5568;
    padding: 1 1;
    height: 1fr;
    margin: 1 2;
}

/* Employees grid */
#e-grid {
    grid-size: 2;
    grid-gutter: 1 2;
    padding: 1 2;
    height: 1fr;
}
.emp-card {
    border: tall #4A5568;
    padding: 1 1;
    height: auto;
    background: #161B22;
}
.emp-header {
    height: auto;
}
.emp-photo {
    width: 18;
    height: 8;
    margin-right: 1;
}
.emp-info {
    width: 1fr;
    height: auto;
}
.emp-body {
    margin-top: 1;
    padding-top: 1;
    border-top: tall #4A5568;
    height: auto;
}

/* Externals get an orange border to distinguish from employees */
.ext-card {
    border: tall #F5A623;
    padding: 1 1;
    height: auto;
    background: #161B22;
}

/* Externals grid */
#x-grid {
    grid-size: 2;
    grid-gutter: 1 2;
    padding: 1 2;
    height: 1fr;
}

/* Pending external promotion inline form */
#p-extform {
    margin-top: 1;
    height: auto;
}
#p-extform Input {
    margin: 1 0;
}

/* Teams screen */
.t-row {
    height: auto;
    margin: 0;
}
.t-row Input, .t-row Select, .t-row Button {
    width: 1fr;
    margin: 0 1 0 0;
    padding: 0 1;
}
.t-row Button {
    width: 14;
    height: 3;
}
#t-table {
    width: 1fr;
    height: 12;
}
#t-detail {
    border: tall #4A5568;
    padding: 1 1;
    height: 12;
}
#t-add-form {
    height: auto;
    padding: 0 1;
}
#t-warning {
    color: #F5D020;
    height: auto;
    margin: 1 0;
}
"""
