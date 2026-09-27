(() => {
  "use strict";
  const report = window.OVH_REPORT;
  const euro = new Intl.NumberFormat("fi-FI", { style: "currency", currency: "EUR" });
  const dateFormat = new Intl.DateTimeFormat("fi-FI");
  const money = cents => euro.format(cents / 100);
  const el = id => document.getElementById(id);
  const text = (tag, value, className) => {
    const node = document.createElement(tag);
    node.textContent = value;
    if (className) node.className = className;
    return node;
  };
  const date = value => value ? dateFormat.format(new Date(`${value}T12:00:00`)) : "–";
  const period = item => item.service_start ? `${date(item.service_start)}–${date(item.service_end)}` : "Kertamaksu";
  const invoicePdfById = new Map((report?.invoices || []).map(invoice => [invoice.invoice_id, invoice.pdf_path]));
  const vatWarningByInvoiceId = new Map((report?.vat?.warnings || []).map(warning => [warning.invoice_id, warning]));
  let withoutVat = true;
  const selectedCents = value => withoutVat
    ? (value.excl_vat_cents ?? value.total_excl_vat_cents)
    : (value.incl_vat_cents ?? value.total_incl_vat_cents);
  const priceModeLabel = () => withoutVat ? "alv 0 %" : "sis. ALV";
  const invoiceLink = (invoiceId, sourceFile) => {
    const link = text("a", invoiceId, "invoice-link");
    const encodedPath = invoicePdfById.get(invoiceId).split("/").map(part => encodeURIComponent(part)).join("/");
    link.href = encodedPath;
    link.target = "_blank";
    link.rel = "noopener";
    link.title = `Avaa ${sourceFile}`;
    return link;
  };

  function renderSummary() {
    const summary = report.summary;
    el("total-incl").textContent = money(summary.total_incl_vat_cents);
    el("total-excl").textContent = money(summary.total_excl_vat_cents);
    el("total-vat").textContent = money(summary.vat_cents);
    el("source-count").textContent = `${summary.invoice_count} laskua`;
    el("report-period").textContent = `${summary.first_month}–${summary.last_month} · ${summary.line_item_count.toLocaleString("fi-FI")} täsmäytettyä laskuriviä`;
    el("generated-at").textContent = `Muodostettu ${new Date(report.generated_at).toLocaleString("fi-FI")}`;
  }

  function renderChart() {
    const x = report.months.map(month => month.month);
    const mode = priceModeLabel();
    const vatMarkerMonth = report.vat?.standard_rate_change?.date?.slice(0, 7);
    const traces = report.services
      .filter(service => report.months.some(month => month.groups.some(group => group.id === service.id)))
      .map(service => ({
        type: "bar",
        name: service.label,
        x,
        y: report.months.map(month => {
          const group = month.groups.find(value => value.id === service.id);
          return group ? selectedCents(group) / 100 : 0;
        }),
        marker: { color: service.color },
        hovertemplate: `<b>${service.label}</b><br>%{x}<br>%{y:.2f} € (${mode})<extra></extra>`,
      }));
    traces.push({
      type: "scatter",
      mode: "lines+markers",
      name: "Yhteensä",
      x,
      y: report.months.map(month => selectedCents(month) / 100),
      line: { color: "#17212b", width: 2 },
      marker: { color: "#17212b", size: 5 },
      hovertemplate: `<b>Yhteensä</b><br>%{x}<br>%{y:.2f} € (${mode})<extra></extra>`,
    });
    const layout = {
      barmode: "relative",
      bargap: 0.18,
      margin: { l: 62, r: 20, t: 10, b: 80 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: getComputedStyle(document.body).fontFamily, color: "#33404c", size: 12 },
      legend: { orientation: "h", y: -0.22, x: 0, traceorder: "normal" },
      xaxis: { type: "category", tickangle: -45, gridcolor: "#edf0f3", fixedrange: true },
      yaxis: { title: "€ / kk", rangemode: "tozero", gridcolor: "#e3e7eb", zerolinecolor: "#aeb8c2", fixedrange: true },
      hovermode: "x unified",
      shapes: !withoutVat && vatMarkerMonth ? [{
        type: "line", xref: "x", yref: "paper", x0: vatMarkerMonth, x1: vatMarkerMonth, y0: 0, y1: 1,
        line: { color: "#8b641d", width: 1.5, dash: "dot" },
      }] : [],
      annotations: !withoutVat && vatMarkerMonth ? [{
        xref: "x", yref: "paper", x: vatMarkerMonth, y: 0.98, yanchor: "top", showarrow: false,
        text: "Yleinen ALV 25,5 %", font: { color: "#5f6870", size: 10 }, bgcolor: "rgba(255,255,255,.9)",
      }] : [],
    };
    const chart = el("billing-chart");
    const plot = chart.dataset.rendered ? Plotly.react : Plotly.newPlot;
    plot(chart, traces, layout, {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["select2d", "lasso2d", "zoomIn2d", "zoomOut2d", "autoScale2d"],
      locale: "fi",
    }).then(graph => {
      chart.dataset.rendered = "true";
      if (typeof graph.removeAllListeners === "function") graph.removeAllListeners("plotly_click");
      graph.on("plotly_click", event => {
        const month = event.points?.[0]?.x;
        if (month) {
          el("month-select").value = month;
          renderMonth(month);
          el("month-title").scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    });
    el("chart-note").textContent = `${withoutVat ? "Veroton" : "Verollinen"} summa. Palkki näyttää palveluryhmät ja viiva kokonaiskulun.`;
  }

  function createLineTable(items) {
    const wrap = document.createElement("div");
    wrap.className = "table-scroll";
    const table = document.createElement("table");
    const head = document.createElement("thead");
    const header = document.createElement("tr");
    ["Palvelu / komponentti", "Jakso", "Lasku", `Hinta (${priceModeLabel()})`].forEach((label, index) => {
      const th = text("th", label, index > 2 ? "num" : "");
      header.append(th);
    });
    head.append(header);
    const body = document.createElement("tbody");
    items
      .slice()
      .sort((a, b) => a.description.localeCompare(b.description, "fi") || a.invoice_id.localeCompare(b.invoice_id))
      .forEach(item => {
        const row = document.createElement("tr");
        const description = document.createElement("td");
        description.className = "description";
        description.append(text("span", item.description));
        description.append(document.createElement("br"));
        const meta = text("span", `${item.action} · ${item.resource_id || "ei resurssitunnusta"}`, "resource");
        description.append(meta);
        row.append(description);
        row.append(text("td", period(item)));
        const invoice = document.createElement("td");
        invoice.append(invoiceLink(item.invoice_id, item.source_file));
        invoice.append(document.createElement("br"));
        invoice.append(text("span", item.source_file, "resource"));
        row.append(invoice);
        row.append(text("td", money(selectedCents(item)), "num"));
        body.append(row);
      });
    table.append(head, body);
    wrap.append(table);
    return wrap;
  }

  function renderMonth(monthKey) {
    const month = report.months.find(value => value.month === monthKey);
    if (!month) return;
    el("month-title").textContent = `${month.label}: palvelut ja laskurivit`;
    const totals = el("month-totals");
    totals.replaceChildren();
    const totalsInOrder = withoutVat
      ? [["Veroton", month.excl_vat_cents], ["ALV", month.vat_cents], ["Verollinen", month.incl_vat_cents]]
      : [["Verollinen", month.incl_vat_cents], ["Veroton", month.excl_vat_cents], ["ALV", month.vat_cents]];
    totalsInOrder.forEach(([label, value]) => {
      const item = text("span", `${label}:`);
      item.append(text("strong", money(value)));
      totals.append(item);
    });
    const target = el("month-breakdown");
    target.replaceChildren();
    if (!month.groups.length) {
      target.append(text("p", "Kuukaudelle ei kohdistu palveluita.", "empty"));
      return;
    }
    month.groups.forEach(group => {
      const details = document.createElement("details");
      details.className = "group";
      details.style.setProperty("--group-color", group.color);
      const summary = document.createElement("summary");
      summary.append(text("span", group.label, "group__title"));
      summary.append(text("span", `${group.items.length} laskuriviä · ${priceModeLabel()}`, "group__meta"));
      summary.append(text("span", money(selectedCents(group)), "group__amount"));
      const body = document.createElement("div");
      body.className = "group__body";
      body.append(createLineTable(group.items));
      details.append(summary, body);
      target.append(details);
    });
  }

  function renderMonthPicker() {
    const select = el("month-select");
    report.months.forEach(month => {
      const option = document.createElement("option");
      option.value = month.month;
      option.textContent = `${month.label} · ${money(selectedCents(month))}`;
      select.append(option);
    });
    const latest = report.months.at(-1)?.month;
    if (latest) {
      select.value = latest;
      renderMonth(latest);
    }
    select.addEventListener("change", () => renderMonth(select.value));
  }

  function updateMonthPickerPrices() {
    const select = el("month-select");
    report.months.forEach((month, index) => {
      select.options[index].textContent = `${month.label} · ${money(selectedCents(month))}`;
    });
  }

  function renderInvoices() {
    const target = el("invoice-years");
    target.replaceChildren();
    const years = new Map();
    report.invoices.forEach(invoice => {
      const year = invoice.issue_date.slice(0, 4);
      if (!years.has(year)) years.set(year, []);
      years.get(year).push(invoice);
    });
    [...years.entries()].sort(([a], [b]) => b.localeCompare(a)).forEach(([year, invoices]) => {
      const details = document.createElement("details");
      details.className = "invoice-year";
      const summary = document.createElement("summary");
      summary.append(text("span", year, "invoice-year__title"));
      const annualTotal = invoices.reduce((sum, invoice) => sum + selectedCents(invoice), 0);
      summary.append(text(
        "span",
        `${invoices.length} laskua · ${money(annualTotal)} (${priceModeLabel()})`,
        "invoice-year__meta",
      ));

      const wrap = document.createElement("div");
      wrap.className = "table-scroll";
      const table = document.createElement("table");
      const head = document.createElement("thead");
      const header = document.createElement("tr");
      ["Lasku", "Päivä", "Tyyppi", "Veroton", "ALV", "Verollinen", "Rivejä"].forEach((label, index) => {
        header.append(text("th", label, index > 2 ? "num" : ""));
      });
      head.append(header);
      const body = document.createElement("tbody");
      invoices.slice().reverse().forEach(invoice => {
        const row = document.createElement("tr");
        const invoiceCell = document.createElement("td");
        invoiceCell.append(invoiceLink(invoice.invoice_id, invoice.source_file));
        row.append(invoiceCell);
        row.append(text("td", date(invoice.issue_date)));
        const type = document.createElement("td");
        type.append(text("span", invoice.bill_type, "pill"));
        row.append(type);
        row.append(text("td", money(invoice.total_excl_vat_cents), "num"));
        const vatCell = text("td", `${money(invoice.vat_cents)} (${invoice.vat_rate_percent} %)`, "num");
        const warning = vatWarningByInvoiceId.get(invoice.invoice_id);
        if (warning) {
          vatCell.append(text(
            "span",
            `Laskun kanta ${warning.billed_rate_percent} %; yleinen kanta ${warning.expected_standard_rate_percent} % 1.9.2024 alkaen`,
            "vat-inline-note",
          ));
        }
        row.append(vatCell);
        row.append(text("td", money(invoice.total_incl_vat_cents), "num"));
        row.append(text("td", String(invoice.items.length), "num"));
        body.append(row);
      });
      table.append(head, body);
      wrap.append(table);
      details.append(summary, wrap);
      target.append(details);
    });
  }

  if (!report || report.schema_version !== 1) {
    document.body.textContent = "Raporttiaineisto puuttuu tai sen versio ei ole tuettu.";
    return;
  }
  renderSummary();
  renderChart();
  renderMonthPicker();
  renderInvoices();
  el("vat-toggle").addEventListener("change", event => {
    withoutVat = !event.currentTarget.checked;
    renderChart();
    updateMonthPickerPrices();
    renderMonth(el("month-select").value);
    renderInvoices();
  });
})();
