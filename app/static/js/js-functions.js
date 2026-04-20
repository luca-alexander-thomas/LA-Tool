function changeImage(imageName) {
    document.getElementById("displayImage").src = imageName;
}

function expandRow(rowID, iconID, rotateClass) {    
    const row = document.getElementById(rowID);
    const icon = document.getElementById(iconID);

    const isNowVisible = row.classList.toggle('hidden') === true;

    icon.classList.toggle(rotateClass, isNowVisible);
}

function updateValueField(sliderID, valueID) {
    document.getElementById(valueID).textContent = document.getElementById(sliderID).value;
}



function getParent(group) {
  return document.querySelector(`.parent-checkbox[data-group="${group}"]`);
}

function getChildren(group) {
  return Array.from(document.querySelectorAll(`.child-checkbox[data-group="${group}"]`));
}

function updateParentState(group) {
  const parent = getParent(group);
  const children = getChildren(group);

  if (!parent || children.length === 0) return;

  const checkedCount = children.filter(c => c.checked).length;

  if (checkedCount === 0) {
    parent.checked = false;
    parent.indeterminate = false;
  } else if (checkedCount === children.length) {
    parent.checked = true;
    parent.indeterminate = false;
  } else {
    parent.checked = false;        // übliches Verhalten
    parent.indeterminate = true;   // Zwischenzustand
  }
}

function setChildren(group, checked) {
  const children = getChildren(group);
  children.forEach(c => { c.checked = checked; });
}

document.addEventListener("change", (e) => {
  const el = e.target;
  if (!(el instanceof HTMLInputElement) || el.type !== "checkbox") return;

  // Parent -> Children
  if (el.classList.contains("parent-checkbox")) {
    const group = el.dataset.group;
    el.indeterminate = false;        // wenn User parent klickt, nie indeterminate lassen
    setChildren(group, el.checked);
    updateParentState(group);
  }

  // Child -> Parent
  if (el.classList.contains("child-checkbox")) {
    const group = el.dataset.group;
    updateParentState(group);
  }
});

// Initialzustand (falls serverseitig schon Checks gesetzt sind)
document.querySelectorAll(".parent-checkbox").forEach(p => updateParentState(p.dataset.group));


function getLetter(index) {
    return String.fromCharCode(65 + index); // 65 = "A"
}

function updateLetters(answerContainer) {
  // NUR die direkten Antwort-Zeilen im Container (nicht andere Elemente)
  const rows = Array.from(answerContainer.children);

  rows.forEach((row, index) => {
    const letterEl = row.querySelector(".answer-letter");
    if (letterEl) letterEl.textContent = getLetter(index);
  });
}

function addAnswer(btn) {
    const answerContainer = btn.previousElementSibling;
    const count = answerContainer.children.length; // wie viele Antworten schon da sind
    const letter = getLetter(count);
    
    answerContainer.insertAdjacentHTML('beforeend', `<div class="d-flex flex-row align-items-center mt-2">
    <div class="col col-xl-1 d-flex justify-content-center"><span class="answer-letter">${letter}</span></div>
    <div class="col"><input class="w-100" type="text" /></div>
    <div class="col col-xl-1 text-danger d-flex justify-content-center align-items-center" onclick="deleteAnswer(this)"><svg class="bi bi-dash-circle-fill" xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" fill="currentColor" viewBox="0 0 16 16" style="font-size: 23px;">
            <path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0M4.5 7.5a.5.5 0 0 0 0 1h7a.5.5 0 0 0 0-1z"></path>
        </svg></div>
</div>`);
}

function deleteAnswer(el) {
  const row = el.parentElement;       // die Antwort-Zeile
  const container = row.parentElement; // #answer-div-...

  row.remove();
  updateLetters(container);
}

function deleteQuestion(pelement) {
    pelement.parentElement.remove();
};

function addQuestion(btn) {
    const container = btn.closest('.tab-pane').querySelector('[id^="div-questions"]');

    container.insertAdjacentHTML('beforeend', `
        <div class="border rounded-1 border-1 border-secondary w-100 p-2 mt-2"><input class="w-25 pt-0 mb-2" type="text" placeholder="Nummer" /><input class="w-100 mb-2" type="text" placeholder="Frage" name="question" /><textarea class="w-100" placeholder="Hinweise / Hilfe"></textarea>
    <div id="answer-div-1">
        <div class="d-flex flex-row align-items-center mt-2">
            <div class="col col-xl-1 d-flex justify-content-center"><span class="answer-letter">A</span></div>
            <div class="col"><input class="w-100" type="text" /></div>
            <div class="col col-xl-1 text-danger d-flex justify-content-center align-items-center" onclick="deleteAnswer(this)"><svg class="bi bi-dash-circle-fill" xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" fill="currentColor" viewBox="0 0 16 16" style="font-size: 23px;">
                    <path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0M4.5 7.5a.5.5 0 0 0 0 1h7a.5.5 0 0 0 0-1z"></path>
                </svg></div>
        </div>
    </div>
    <div class="d-flex justify-content-center mt-2" onclick="addAnswer(this)"><svg class="bi bi-plus-circle text-success" xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" fill="currentColor" viewBox="0 0 16 16" style="font-size: 23px;">
            <path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14m0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16"></path>
            <path d="M8 4a.5.5 0 0 1 .5.5v3h3a.5.5 0 0 1 0 1h-3v3a.5.5 0 0 1-1 0v-3h-3a.5.5 0 0 1 0-1h3v-3A.5.5 0 0 1 8 4"></path>
        </svg></div><button class="btn btn-primary text-bg-danger border-danger" type="button" onclick="deleteQuestion(this)">Löschen</button>
</div>
    `);
}

function addExercise(btn) {
    const container = btn.closest('.tab-pane').querySelector('[id^="div-tasks"]');

    container.insertAdjacentHTML('beforeend', `
        <div class="border rounded-1 border-1 border-secondary d-flex flex-column align-items-start p-2 mb-2"><input class="w-100 mb-2" type="text" placeholder="Aufgabe" /><textarea class="w-100 mb-2" placeholder="Beschreibung"></textarea><textarea class="w-100 mb-2" placeholder="Hinweise"></textarea><label class="form-label">Aufgabe PDF <input type="file" /></label><button class="btn btn-primary text-bg-danger border-danger" type="button" onclick="deleteQuestion(this)">Löschen</button></div>
    `);
}

tinymce.init({
        selector: '#mytextarea'
      });

