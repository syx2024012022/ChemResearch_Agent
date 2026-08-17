const state = { sessionId:null, document:null, question:null, selected:null, artifact:null, retryPresentation:false };
const $ = (id) => document.getElementById(id);

function show(id) { $(id).classList.remove("hidden"); }
function setStage(stage) { document.querySelectorAll("[data-stage]").forEach(x => x.classList.toggle("active", x.dataset.stage === stage)); }
function setStatus(text) { $("session-status").textContent = text; }
function notify(text, error=false) { const node=$("message"); node.textContent=text; node.className=`message${error?" error":""}`; setTimeout(()=>node.classList.add("hidden"),5000); }
async function api(path, options={}) { const response=await fetch(path,options); if(!response.ok){let detail=`HTTP ${response.status}`;try{detail=(await response.json()).detail||detail;}catch{} throw new Error(detail);} return response.json(); }
function busy(button, value, label="处理中…") { button.disabled=value; if(value){button.dataset.label=button.textContent;button.textContent=label;}else if(button.dataset.label){button.textContent=button.dataset.label;} }

function updateSourceButton(){ $("upload-button").disabled=!$("paper-file").files[0]&&!$("paper-source").value.trim(); }
$("paper-file").addEventListener("change", e => { const file=e.target.files[0]; $("file-name").textContent=file?file.name:"尚未选择文件"; if(file)$("paper-source").value=""; updateSourceButton(); });
$("paper-source").addEventListener("input",()=>{if($("paper-source").value.trim()){$("paper-file").value="";$("file-name").textContent="尚未选择文件";}updateSourceButton();});
$("upload-button").addEventListener("click", async () => {
  const button=$("upload-button"), file=$("paper-file").files[0], identifier=$("paper-source").value.trim(); busy(button,true,"解析中…");
  try {
    const session=await api("/v1/sessions",{method:"POST"}); state.sessionId=session.session_id;
    let result;
    if(file){const body=new FormData();body.append("file",file);result=await api(`/v1/sessions/${state.sessionId}/documents`,{method:"POST",body});}
    else {const paper=await api("/v1/papers/resolve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({identifier})});if(!paper.pdf_url)throw new Error("已找到论文题录，但没有合法开放 PDF。请上传论文文件。");const filename=`${paper.doi||"paper"}.pdf`.replaceAll("/","_");result=await api(`/v1/sessions/${state.sessionId}/documents/url`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:paper.pdf_url,filename})});}
    state.document=result.document;
    $("document-summary").textContent=`${result.document.file_name} · ${result.document.page_count} 页 · ${result.document.figures.length} 个视觉对象`;
    show("analysis-panel"); setStage("analysis"); setStatus("PDF 已解析"); $("analysis-panel").scrollIntoView({behavior:"smooth"});
  } catch(e) { notify(e.message,true); } finally { busy(button,false); }
});

$("analysis-button").addEventListener("click", async () => {
  const button=$("analysis-button"); busy(button,true,"分析中…");
  try {
    const result=await api(`/v1/sessions/${state.sessionId}/analysis`,{method:"POST"});
    const a=result.analysis; $("analysis-summary").innerHTML=`<strong>${escapeHtml(a.metadata.title||"论文分析完成")}</strong><br>已提取 ${a.innovations.length} 条创新点、${a.key_results.length} 条关键结果和 ${a.reactions.length} 个反应记录。`;
    const interview=await api(`/v1/sessions/${state.sessionId}/requirements/interview`,{method:"POST"});
    show("interview-panel"); renderQuestion(interview.question); setStage("interview"); setStatus("等待汇报要求"); $("interview-panel").scrollIntoView({behavior:"smooth"});
  } catch(e) { notify(e.message,true); } finally { busy(button,false); }
});

function renderQuestion(question) {
  state.question=question; state.selected=question.input_kind==="multi_choice"?[]:null;
  const recommendation=question.recommendation?`<p class="recommendation">${escapeHtml(question.recommendation)}</p>`:"";
  let control="";
  if(question.input_kind==="text") control=`<textarea id="answer-text" class="text-answer" rows="4" placeholder="请输入你的要求"></textarea>`;
  else if(question.input_kind==="boolean") control=`<div class="option-grid"><button class="option" data-value="true">是</button><button class="option" data-value="false">否</button></div>`;
  else control=`<div class="option-grid">${question.options.map(o=>`<button class="option" data-value="${escapeAttr(o.value)}">${escapeHtml(o.label)}${o.description?` · ${escapeHtml(o.description)}`:""}${o.recommended?'<span class="badge">推荐</span>':""}</button>`).join("")}</div>`;
  $("question-card").innerHTML=`<h3>${escapeHtml(question.prompt)}</h3>${recommendation}${control}<div class="answer-actions"><button id="answer-button" class="primary" disabled>继续</button></div>`;
  document.querySelectorAll(".option").forEach(btn=>btn.addEventListener("click",()=>selectOption(btn)));
  const text=$("answer-text"); if(text) text.addEventListener("input",()=>$("answer-button").disabled=!text.value.trim());
  $("answer-button").addEventListener("click",submitAnswer);
}
function selectOption(button) {
  const value=button.dataset.value, multi=state.question.input_kind==="multi_choice";
  if(multi){ const i=state.selected.indexOf(value); if(i>=0)state.selected.splice(i,1);else state.selected.push(value); button.classList.toggle("selected"); }
  else { state.selected=state.question.input_kind==="boolean"?value==="true":value; document.querySelectorAll(".option").forEach(x=>x.classList.toggle("selected",x===button)); }
  $("answer-button").disabled=multi?state.selected.length===0:state.selected===null;
}
async function submitAnswer() {
  const button=$("answer-button"), text=$("answer-text"); const value=text?text.value.trim():state.selected; busy(button,true);
  try {
    const result=await api(`/v1/sessions/${state.sessionId}/requirements/interview/answer`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({step:state.question.step,value})});
    if(result.question) renderQuestion(result.question); else { await createPlan(); }
  } catch(e) { notify(e.message,true); busy(button,false); }
}
async function createPlan() {
  setStatus("正在规划"); const session=await api(`/v1/sessions/${state.sessionId}/plan`,{method:"POST"}); renderPlan(session.slide_plan); $("question-card").innerHTML='<h3>汇报要求已确认</h3><p class="recommendation">已根据你的选择生成规划；后续可在规划区提出修改意见。</p>'; show("plan-panel"); setStage("planning"); setStatus("等待规划批准"); $("plan-panel").scrollIntoView({behavior:"smooth"});
}
function renderPlan(plan) { $("plan-summary").innerHTML=plan.slides.map((s,i)=>`<article class="plan-card"><small>SLIDE ${i+1} · ${escapeHtml(s.slide_type)}</small><h3>${escapeHtml(s.key_message)}</h3><p>${escapeHtml(s.purpose)}</p></article>`).join(""); }
$("revision-button").addEventListener("click",async()=>{ const reason=$("revision-reason").value.trim(); if(!reason)return notify("请先填写修改意见。",true); try{await api(`/v1/sessions/${state.sessionId}/plan/revision`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({reason})}); const session=await api(`/v1/sessions/${state.sessionId}/plan`,{method:"POST"}); renderPlan(session.slide_plan); $("revision-reason").value=""; notify("规划已重新生成，请再次检查。");}catch(e){notify(e.message,true);} });
$("approval-button").addEventListener("click",async()=>{ try{await api(`/v1/sessions/${state.sessionId}/plan/approval`,{method:"POST"}); show("presentation-panel"); setStage("presentation"); setStatus("规划已批准"); $("presentation-panel").scrollIntoView({behavior:"smooth"});}catch(e){notify(e.message,true);} });
$("generate-button").addEventListener("click",async()=>{const button=$("generate-button");busy(button,true,"任务已提交");setStatus("正在生成 PPT");show("progress-area");try{const endpoint=state.retryPresentation?"retry":"async";state.retryPresentation=false;await api(`/v1/sessions/${state.sessionId}/presentation/${endpoint}`,{method:"POST"});await pollWorkflowStatus();}catch(e){notify(e.message,true);setStatus("生成失败");if(state.retryPresentation){button.disabled=false;button.textContent="重试生成";}else{busy(button,false);}} });
async function pollWorkflowStatus(){const button=$("generate-button");for(;;){const workflow=await api(`/v1/sessions/${state.sessionId}/workflow-status`);$("progress-bar").style.width=`${workflow.progress}%`;$("progress-message").textContent=workflow.message;setStatus(workflow.message);if(workflow.status==="completed"){const artifact=await api(`/v1/sessions/${state.sessionId}/presentation`);state.artifact=artifact;renderArtifact(artifact);busy(button,false);button.textContent="生成完成";button.disabled=true;return;}if(workflow.stage==="validation_failed"){const artifact=await api(`/v1/sessions/${state.sessionId}/presentation`);state.artifact=artifact;renderArtifact(artifact);state.retryPresentation=false;busy(button,false);button.textContent="重新生成";throw new Error(validationMessage(artifact,workflow.message));}if(workflow.status==="failed_retryable"){state.retryPresentation=true;busy(button,false);button.textContent="重试生成";throw new Error(workflow.error?.message||workflow.message);}if(workflow.status==="failed_final"){busy(button,false);button.disabled=true;throw new Error(workflow.error?.message||workflow.message);}await new Promise(resolve=>setTimeout(resolve,1200));}}
function validationMessage(artifact,fallback){const issues=artifact.validation?.issues||[];if(!issues.length)return fallback;const summary=issues.slice(0,3).map(x=>x.message).join("；");return `${fallback}：${summary}${issues.length>3?`（另有 ${issues.length-3} 项）`:""}`;}
function renderArtifact(artifact){const grid=$("preview-grid");grid.innerHTML="";for(let i=1;i<=artifact.slide_count;i++){const img=document.createElement("img");img.loading="lazy";img.alt=`第 ${i} 页预览`;img.src=`/v1/artifacts/${artifact.artifact_id}/previews/${i}`;grid.appendChild(img);}$("download-link").href=`/v1/artifacts/${artifact.artifact_id}/download`;show("artifact-area");}
function escapeHtml(value){return String(value??"").replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));}
function escapeAttr(value){return escapeHtml(value);}
setStage("upload");
