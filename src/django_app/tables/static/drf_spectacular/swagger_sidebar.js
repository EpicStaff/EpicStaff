"use strict";

// Left-hand endpoint list for the Swagger page. Swagger UI keeps only the on-screen rows of
// its endpoint list in the page, so the browser's Ctrl+F cannot find an endpoint; this list
// holds every endpoint, has its own search, and opens the chosen endpoint in the main pane.
// Relies on `ui`, the SwaggerUIBundle instance created by drf-spectacular's init script.
(function () {
  const sidebar = document.createElement("nav");
  sidebar.id = "endpoint-sidebar";
  sidebar.setAttribute("aria-label", "Endpoints");
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "Search endpoints";
  search.setAttribute("aria-label", "Search endpoints");
  const groups = document.createElement("div");
  sidebar.append(search, groups);
  document.body.prepend(sidebar);

  let renderedSpec;
  let openedOperationKey;
  let activeLink;

  function highlight(link) {
    if (activeLink) {
      activeLink.removeAttribute("aria-current");
    }
    activeLink = link;
    link.setAttribute("aria-current", "true");
  }

  function openOperation(tag, operationId, link) {
    const operationKey = ["operations", tag, operationId];
    if (openedOperationKey) {
      ui.layoutActions.show(openedOperationKey, false);
    }
    openedOperationKey = operationKey;
    // The same steps as Swagger UI's deep-link action, which can't be used here: every
    // operationId contains "_", so it would log a deprecation error and open a second, mangled key.
    ui.layoutActions.show(["operations-tag", tag], true);
    ui.layoutActions.show(operationKey, true);
    ui.layoutActions.scrollTo(operationKey);
    ui.layoutActions.scrollToVirtualizedOperation(operationKey);
    highlight(link);
  }

  function applySearch() {
    const phrase = search.value.trim().toLowerCase();
    // Every word must appear somewhere, in any order: "get secrets" finds "get /api/secrets/".
    const words = phrase.split(/\s+/);
    groups.querySelectorAll("details").forEach(function (group) {
      let matchCount = 0;
      group.querySelectorAll("a").forEach(function (link) {
        const searchedText = (group.dataset.tag + " " + link.textContent + " " + link.title).toLowerCase();
        const matches = words.every(function (word) {
          return searchedText.includes(word);
        });
        link.hidden = !matches;
        matchCount += matches ? 1 : 0;
      });
      group.hidden = matchCount === 0;
      group.open = phrase !== "";
    });
  }

  function render() {
    // The schema is downloaded again after Authorize / Logout; rebuild only when it changed.
    const spec = ui.specSelectors.specJson();
    if (spec === renderedSpec) {
      return;
    }
    renderedSpec = spec;
    groups.textContent = "";
    ui.specSelectors.taggedOperations().forEach(function (tagDetails, tag) {
      const operations = tagDetails.get("operations");
      const group = document.createElement("details");
      group.dataset.tag = tag;
      const groupTitle = document.createElement("summary");
      groupTitle.textContent = tag + " (" + operations.size + ")";
      group.append(groupTitle);
      operations.forEach(function (operation) {
        const operationId = operation.getIn(["operation", "operationId"]);
        const link = document.createElement("a");
        link.href = "#/" + encodeURIComponent(tag) + "/" + encodeURIComponent(operationId);
        link.title = operation.getIn(["operation", "summary"]) || "";
        const method = document.createElement("span");
        method.className = "method method-" + operation.get("method");
        method.textContent = operation.get("method");
        link.append(method, " " + operation.get("path"));
        link.addEventListener("click", function (event) {
          event.preventDefault();
          openOperation(tag, operationId, link);
        });
        // A rebuild after Authorize / Logout keeps the open endpoint highlighted.
        if (openedOperationKey && openedOperationKey[1] === tag && openedOperationKey[2] === operationId) {
          highlight(link);
        }
        group.append(link);
      });
      groups.append(group);
    });
    applySearch();
  }

  search.addEventListener("input", applySearch);
  ui.getStore().subscribe(render);
  render();
})();
