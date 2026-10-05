"use strict";
(() => {
  const sample = JSON.parse(document.getElementById("scenario-data").textContent);
  const audience = document.getElementById("audience");
  const concern = document.getElementById("concern");
  const context = document.getElementById("context-copy");
  const progress = document.getElementById("scenario-progress");
  const question = document.getElementById("scenario-question");
  const choices = document.getElementById("scenario-choices");
  const takeaway = document.getElementById("scenario-takeaway");
  const next = document.getElementById("scenario-next");
  let step = -1;
  let selected = null;
  const guides = {access:"Seek dated permission evidence. Unsupported access remains unknown.",ownership:"Name the decision owner and reason. A proposal authorizes no execution.",changes:"Compare input paths and rule versions separately. A changed result alone does not establish causation."};
  const update = () => {context.textContent = sample.audiences[audience.value];document.getElementById("guide").textContent = guides[concern.value] || "Start with one workflow, its owner and the evidence you have. Leave unsupported facts unknown.";};
  const showStep = () => {
    selected = null; next.disabled = true; choices.replaceChildren(); takeaway.textContent = "Choose an example evidence state, or skip this question.";
    progress.textContent = "Synthetic scenario · step " + (step + 1) + " of " + sample.steps.length;
    question.textContent = sample.steps[step].question;
    sample.steps[step].choices.forEach(choice => {
      const button = document.createElement("button");button.type="button";button.textContent=choice.label;button.setAttribute("aria-pressed","false");
      button.addEventListener("click",() => {selected=choice.id;choices.querySelectorAll("button").forEach(item => item.setAttribute("aria-pressed",String(item===button)));takeaway.textContent=choice.takeaway;next.disabled=false;});
      choices.append(button);
    });
    next.textContent = step + 1 === sample.steps.length ? "Complete synthetic scenario" : "Next evidence question";
  };
  const advance = () => {
    step += 1;
    if (step < sample.steps.length) {showStep();question.focus();return;}
    progress.textContent="Synthetic scenario complete · educational takeaway only";question.textContent="Keep supported facts and unknowns distinct";choices.replaceChildren();next.disabled=true;document.getElementById("scenario-skip").disabled=true;
    takeaway.textContent="Your example choices establish no facts about your systems. Record dated evidence and a scoped, accountable next decision. No provider action was taken.";question.focus();
  };
  document.getElementById("scenario-start").addEventListener("click",event => {event.target.disabled=true;document.getElementById("scenario-flow").hidden=false;advance();});
  next.addEventListener("click",() => {if(selected!==null) advance();});
  document.getElementById("scenario-skip").addEventListener("click",advance);
  const clear = () => {concern.value="";document.getElementById("context").value="";document.getElementById("details").value="";step=-1;selected=null;document.getElementById("scenario-flow").hidden=true;document.getElementById("scenario-start").disabled=false;document.getElementById("scenario-skip").disabled=false;choices.replaceChildren();takeaway.textContent="";update();};
  audience.addEventListener("change",update);concern.addEventListener("change",update);
  document.getElementById("clear").addEventListener("click",clear);
  window.addEventListener("pagehide",clear);
  update();
})();
