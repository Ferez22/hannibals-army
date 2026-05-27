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

/* Browser + Pending split: table on left (50%), detail on right (50%) */
#b-table, #p-table {
    width: 50%;
    height: 1fr;
}
#b-detail, #p-detail {
    width: 50%;
    height: 1fr;
    border: tall #4A5568;
    padding: 0 1;
}
#p-actions {
    height: 3;
    align-horizontal: left;
    width: 50%;
}
#p-actions Button {
    width: 14;
    margin: 0 1;
}

/* Ingest input row layout */
Horizontal {
    height: auto;
}
"""
