/* 离线演示运行时：翻页、目录、备注、打印与原生 SVG 图表。 */
(() => {
  'use strict';
  const deck = document.querySelector('.deck');
  const slides = Array.from(document.querySelectorAll('section.slide'));
  if (!deck || !slides.length) return;
  const node = (tag, text, cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  const svgNode = (tag, attrs={}, text) => {const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;};
  document.querySelectorAll('.kpi-grid,.process').forEach(g=>g.style.setProperty('--columns',g.children.length));
  document.querySelectorAll('.sources').forEach(g=>{const n=g.querySelectorAll('.source-item').length;if(n>4){g.classList.add('dense');g.style.setProperty('--source-cols',n>6?3:2);}});
  const blueprint=document.body.dataset.template==='knowledge-arch-blueprint';
  if(blueprint){
    const aliases=[['.eyebrow','kb-kicker'],['h1,h2','kb-h1'],['.lede','kb-sub'],['.card','kb-card'],['.process','kb-pipeline'],['.step','kb-step'],['.step-no','kb-step-num'],['.step h3','kb-step-title'],['.step p','kb-step-body']];
    aliases.forEach(([selector,cls])=>deck.querySelectorAll(selector).forEach(el=>el.classList.add(cls)));
    slides.forEach(slide=>{if(!slide.querySelector('.kb-grid-bg'))slide.prepend(node('div',undefined,'kb-grid-bg'));});
  }
  const themeStyle=getComputedStyle(document.body);
  const colors=['--series-1','--series-2'].map((key,i)=>themeStyle.getPropertyValue(key).trim()||['#087f82','#b17448'][i]);
  const axis = (values, bar) => {
    let lo=Math.min(...values),hi=Math.max(...values);
    if(bar){lo=Math.min(0,lo);hi=Math.max(0,hi);}else{const pad=(hi-lo||Math.abs(hi)*.1||1)*.18;lo-=pad;hi+=pad;if(Math.min(...values)>=0)lo=Math.max(0,lo);}
    const span=hi-lo||1,pow=10**Math.floor(Math.log10(span/4)),ratio=span/4/pow;
    const step=(ratio<=1?1:ratio<=2?2:ratio<=5?5:10)*pow;
    const min=Math.floor(lo/step)*step,max=Math.ceil(hi/step)*step;
    return {min,max:max===min?min+step:max,step};
  };
  const tick = n => Number(n.toPrecision(8)).toLocaleString('zh-CN',{maximumFractionDigits:5});
  function renderCharts(){document.querySelectorAll('.chart-panel').forEach(panel => {
    panel.querySelectorAll('svg,.chart-legend,.chart-note').forEach(n=>n.remove());
    const dataNode=panel.querySelector('script.chart-data');if(!dataNode)return;
    try {
      const d=JSON.parse(dataNode.textContent),all=d.series.flatMap(s=>s.values),a=axis(all,d.kind==='bar');
      const legend=node('div',undefined,'chart-legend');
      d.series.forEach((s,i)=>{const n=node('span',s.name);n.style.setProperty('--series',colors[i]);legend.append(n);});panel.append(legend);
      panel.append(node('div',d.unit+(d.kind==='line'&&a.min>0?' · 纵轴非零起点':''),'chart-note'));
      const mobile=innerWidth<=600;
      const svg=svgNode('svg',{viewBox:mobile?'0 0 640 420':'0 0 1040 360',role:'img','aria-label':d.series.map(s=>s.name).join('、')+'，单位'+d.unit});
      const left=mobile?100:88,right=mobile?600:1005,top=mobile?55:35,bottom=mobile?340:292,w=right-left,h=bottom-top,n=d.categories.length;
      const y=v=>bottom-(v-a.min)/(a.max-a.min)*h;
      const x=i=>d.kind==='bar'?left+w*(i+.5)/n:left+w*i/(n-1);
      for(let i=0;i<9;i++){const v=a.min+i*a.step;if(v>a.max+a.step*.01)break;svg.append(svgNode('line',{x1:left,y1:y(v),x2:right,y2:y(v),class:'chart-grid'}));svg.append(svgNode('text',{x:left-14,y:y(v)+5,'text-anchor':'end',class:'chart-label'},tick(v)));}
      d.categories.forEach((c,i)=>svg.append(svgNode('text',{x:x(i),y:bottom+35,'text-anchor':'middle',class:'chart-label'},c)));
      d.series.forEach((s,si)=>{
        if(d.kind==='line')svg.append(svgNode('polyline',{points:s.values.map((v,i)=>x(i)+','+y(v)).join(' '),fill:'none',stroke:colors[si],'stroke-width':3.5,'stroke-linejoin':'round','stroke-linecap':'round'}));
        s.values.forEach((v,i)=>{
          const px=x(i),py=y(v),label=s.name+' / '+d.categories[i]+'：'+v+' '+d.unit;
          if(d.kind==='bar'){
            const bw=Math.min(60,w/n*.65/d.series.length),bx=px+(si-(d.series.length-1)/2)*bw;
            const bar=svgNode('rect',{x:bx-bw*.42,y:Math.min(y(0),py),width:bw*.84,height:Math.max(1,Math.abs(y(0)-py)),rx:3,fill:colors[si]});bar.append(svgNode('title',{},label));svg.append(bar);
            if(n<=6)svg.append(svgNode('text',{x:bx,y:py+(v>=0?-10:21),'text-anchor':'middle',class:'chart-value'},tick(v)));
          }else{
            const dot=svgNode('circle',{cx:px,cy:py,r:5,fill:'white',stroke:colors[si],'stroke-width':3});dot.append(svgNode('title',{},label));svg.append(dot);
            if(n<=6&&d.series.length===1)svg.append(svgNode('text',{x:px,y:py-15,'text-anchor':'middle',class:'chart-value'},tick(v)));
          }
        });
      });panel.append(svg);
    } catch (_) {panel.append(node('p','图表数据不可用，请核对原始材料。','small'));}
  });}
  const nav=node('nav',undefined,'deck-nav');nav.setAttribute('aria-label','演示导航');
  const button=(text,fn)=>{const b=node('button',text);b.type='button';b.addEventListener('click',fn);nav.append(b);return b;};
  let current=0;
  const prev=button('上一页',()=>show(current-1)),counter=node('span','','counter');nav.append(counter);
  const next=button('下一页',()=>show(current+1));
  const outline=node('section',undefined,'deck-outline');outline.hidden=true;outline.setAttribute('aria-label','演示目录');
  const head=node('div',undefined,'outline-head');head.append(node('strong','演示目录'));const close=node('button','关闭');close.onclick=()=>outline.hidden=true;head.append(close);outline.append(head);
  const grid=node('div',undefined,'outline-grid');outline.append(grid);
  const notes=node('aside',undefined,'notes-panel');notes.hidden=true;notes.setAttribute('aria-label','讲解备注');
  const noteHead=node('div',undefined,'outline-head');noteHead.append(node('strong','讲解备注'));const noteClose=node('button','关闭');noteClose.onclick=()=>notes.hidden=true;noteHead.append(noteClose);notes.append(noteHead,node('p',''));
  const toggleOutline=()=>{outline.hidden=!outline.hidden;notes.hidden=true;};
  button('目录',toggleOutline);const notesButton=button('备注',()=>{notes.hidden=!notes.hidden;outline.hidden=true;});
  button('全屏',()=>{if(document.fullscreenElement)document.exitFullscreen?.();else document.documentElement.requestFullscreen?.().catch(()=>{});});
  const progress=node('div',undefined,'deck-progress');
  document.body.append(nav,progress,outline,notes);
  slides.forEach((slide,i)=>{
    const footer=node('footer',undefined,'slide-footer'+(blueprint?' kb-footer':''));footer.append(node('span','大宗商品研究 · 分析演示'),node('span',String(i+1).padStart(2,'0')+' / '+String(slides.length).padStart(2,'0'),'page-index'));slide.append(footer);
    const b=node('button');b.append(node('span',String(i+1).padStart(2,'0')),node('strong',slide.querySelector('h1,h2')?.textContent||'演示页'));b.onclick=()=>{show(i);outline.hidden=true;};grid.append(b);
  });
  function fit(){renderCharts();document.documentElement.style.setProperty('--deck-scale',String(Math.min((innerWidth-32)/1280,(innerHeight-72)/720)));}
  function show(i){current=Math.max(0,Math.min(slides.length-1,i));slides.forEach((s,j)=>{s.classList.toggle('active',j===current);s.setAttribute('aria-hidden',String(j!==current));});counter.textContent=(current+1)+' / '+slides.length;prev.disabled=current===0;next.disabled=current===slides.length-1;document.documentElement.style.setProperty('--progress',((current+1)/slides.length*100)+'%');const text=slides[current].querySelector('.notes')?.textContent.trim()||'';notes.querySelector('p').textContent=text||'本页未提供讲解备注。';notesButton.disabled=!text;history.replaceState(null,'','#/'+(current+1));if(innerWidth<=600)window.scrollTo(0,0);}
  const params=new URLSearchParams(location.search),preview=params.get('preview');
  show((Number(preview||location.hash.replace('#/',''))||1)-1);fit();addEventListener('resize',fit);
  if(preview){nav.hidden=true;nav.style.display='none';progress.style.display='none';}
  addEventListener('keydown',e=>{if(e.target.closest('input,textarea,select,[contenteditable=true]'))return;let handled=true;if(['ArrowRight','PageDown',' '].includes(e.key))show(current+1);else if(['ArrowLeft','PageUp'].includes(e.key))show(current-1);else if(e.key==='Home')show(0);else if(e.key==='End')show(slides.length-1);else if(e.key.toLowerCase()==='o')toggleOutline();else if(e.key.toLowerCase()==='n')notesButton.click();else if(e.key==='Escape'){outline.hidden=true;notes.hidden=true;}else handled=false;if(handled)e.preventDefault();});
  let touchX=0;deck.addEventListener('touchstart',e=>{touchX=e.changedTouches[0].clientX;},{passive:true});deck.addEventListener('touchend',e=>{const delta=e.changedTouches[0].clientX-touchX;if(Math.abs(delta)>70)show(current+(delta<0?1:-1));},{passive:true});
  window.__presentation={show,count:slides.length,get index(){return current;}};
})();
