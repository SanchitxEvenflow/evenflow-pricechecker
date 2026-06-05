export function csvEscape(field: unknown) {
  return `"${String(field).replace(/"/g, '""')}"`;
}

export function downloadCsv(csvContent: string, filename: string, type = "text/csv;charset=utf-8;") {
  const blob = new Blob([csvContent], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.setAttribute("download", filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
