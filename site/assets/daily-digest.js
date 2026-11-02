(()=>{
'use strict';

const SCHEMA_VERSION=1;
const KIND='holodocchi.daily_digest';
const TAIPEI='Asia/Taipei';
const DATE_RE=/^\d{4}-\d{2}-\d{2}$/;

function el(tag,className,text){
  const node=document.createElement(tag);
  if(className)node.className=className;
  if(text!==undefined&&text!==null)node.textContent=String(text);
  return node;
}
function text(value){return value===undefined||value===null?'':String(value).trim()}
function taipeiDay(now=new Date()){
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:TAIPEI,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now);
  const map=Object.fromEntries(parts.map(part=>[part.type,part.value]));
  return map.year+'-'+map.month+'-'+map.day;
}
function displayDay(day){return DATE_RE.test(day)?day.replaceAll('-','/'):day}
function config(){const cfg=window.HOLOVIEWER_CONFIG?.dailyDigest;return cfg&&typeof cfg==='object'?cfg:{}}
function artifactUrl(day){
  const cfg=config();
  const base=text(cfg.base).replace(/\/$/,'');
  const template=text(cfg.pathTemplate);
  if(!template||!DATE_RE.test(day))return '';
  const month=day.slice(0,7);
  const path=template
    .replaceAll('{month}',encodeURIComponent(month))
    .replaceAll('{date}',encodeURIComponent(day));
  if(!path.startsWith('/'))return '';
  return base?base+path:path;
}

const PUBLIC_LAYOUTS=new Set(['brief','lead','split','editorial','compact','rail','timeline','chips']);
const OVERVIEW_LAYOUTS=new Set(['compact','rail','lead']);

function publicText(value){
  return text(value)
    .replace(/\x60[A-Za-z0-9_-]{11}\x60/g,'')
    .replace(/\(\s*\)/g,'')
    .replace(/（\s*）/g,'')
    .replace(/\s{2,}/g,' ')
    .trim();
}
function clampText(value,max=46){
  const raw=publicText(value);
  if(raw.length<=max)return raw;
  return raw.slice(0,Math.max(1,max-1)).trimEnd()+'…';
}
function shortHeadline(value,max=42){
  const raw=publicText(value);
  if(!raw)return '';
  const parts=raw.split(/[：:]/);
  const candidate=parts[0]&&parts[0].length>=8?parts[0]:raw;
  return clampText(candidate,max);
}
function paragraphChunks(value,{min=2,max=3}={}){
  const raw=publicText(value);
  if(!raw)return [];
  const sentences=raw.match(/[^。！？]+[。！？]?/g)?.map(item=>item.trim()).filter(Boolean)||[raw];
  if(sentences.length<=1)return [raw];
  const target=Math.min(max,Math.max(min,Math.ceil(raw.length/150)));
  const size=Math.ceil(sentences.length/target);
  const chunks=[];
  for(let i=0;i<sentences.length;i+=size)chunks.push(sentences.slice(i,i+size).join(''));
  return chunks.slice(0,max);
}
function appendParagraphs(parent,value,className){
  const chunks=paragraphChunks(value);
  chunks.forEach(chunk=>parent.append(el('p',className,chunk)));
}
function appendStoryEditorialCopy(parent,value){
  const chunks=paragraphChunks(value,{min:2,max:5});
  if(chunks.length<3){
    chunks.forEach(chunk=>parent.append(el('p','daily-story-summary',chunk)));
    return;
  }
  const split=Math.ceil(chunks.length/2);
  const columns=el('div','daily-story-summary-columns');
  const left=el('div','daily-story-summary-column');
  const right=el('div','daily-story-summary-column');
  chunks.slice(0,split).forEach(chunk=>left.append(el('p','daily-story-summary',chunk)));
  chunks.slice(split).forEach(chunk=>right.append(el('p','daily-story-summary',chunk)));
  columns.append(left,right);
  parent.append(columns);
}
function storyVisualLayout(count,{largeOrdinal=0,explicit=''}={}){
  const requested=publicText(explicit).toLowerCase();
  if(count>=6&&(requested==='hero-full-carousel'||requested==='mosaic-carousel'))return requested;
  if(count<=1)return 'feature-single-wide';
  if(count===2)return 'duo';
  if(count===3)return 'triptych';
  if(count===4)return 'quad';
  if(count===5)return 'three-two';
  return largeOrdinal%2===0?'hero-full-carousel':'mosaic-carousel';
}
function storyVisual(videoIds,byId,{onSelect=null,layout='six-grid'}={}){
  const ids=storyVisibleIds(videoIds,byId);
  if(!ids.length)return null;

  const shell=el('div','daily-story-visual-shell');
  const visual=el('div','daily-story-visual');
  visual.dataset.count=String(ids.length);
  visual.dataset.visualLayout=layout;
  const cropCycle=['center','upper','left','right','center','upper','left','right','center'];

  ids.forEach((id,index)=>{
    const figure=el('figure','daily-story-visual-item');
    figure.dataset.slot=String(index+1);
    figure.dataset.videoId=id;
    figure.dataset.crop=cropCycle[index%cropCycle.length];
    figure.dataset.page=String(Math.floor(index/5));
    if(onSelect){
      figure.classList.add('is-selectable');
      figure.tabIndex=0;
      figure.setAttribute('role','button');
      const select=()=>{
        visual.querySelectorAll('.daily-story-visual-item').forEach(node=>node.classList.toggle('is-selected',node===figure));
        onSelect(id,index);
      };
      if(index===0)figure.classList.add('is-selected');
      figure.addEventListener('click',select);
      figure.addEventListener('keydown',event=>{
        if(event.key==='Enter'||event.key===' '){
          event.preventDefault();
          select();
        }
      });
    }
    const img=thumbnailImage(id);
    if(img)figure.append(img);
    const row=byId.get(id),name=publicText(row?.channel_name);
    if(name)figure.append(el('figcaption','',name));
    visual.append(figure);
  });

  if((layout==='mosaic-carousel'||layout==='hero-full-carousel')&&ids.length>5){
    let start=0;
    let timer=null;
    const maxStart=Math.max(1,ids.length-5);
    const applyWindow=()=>{
      visual.dataset.windowStart=String(start);
      visual.classList.add('is-changing');
      visual.querySelectorAll('.daily-story-visual-item').forEach((node,index)=>{
        const slot=index-start+1;
        const visible=slot>=1&&slot<=5;
        node.hidden=!visible;
        if(visible)node.dataset.slot=String(slot);
      });
      requestAnimationFrame(()=>requestAnimationFrame(()=>visual.classList.remove('is-changing')));
    };
    const rotate=()=>{
      start=start>=maxStart?0:start+1;
      applyWindow();
    };
    const startRotation=()=>{
      if(timer)clearInterval(timer);
      timer=setInterval(rotate,5000);
    };
    applyWindow();
    startRotation();
    shell.addEventListener('mouseenter',()=>{if(timer){clearInterval(timer);timer=null}});
    shell.addEventListener('mouseleave',startRotation);
    shell.append(visual);
  }else{
    shell.append(visual);
  }
  return shell;
}
function publicLayout(source,fallback){
  const requested=text(source?.layout_template||source?.display_template||source?.layout).toLowerCase();
  return PUBLIC_LAYOUTS.has(requested)?requested:fallback;
}
function streamMap(artifact){
  return new Map((Array.isArray(artifact?.streams)?artifact.streams:[]).map(row=>[String(row?.video_id||''),row]));
}
function youtubeUrl(videoId){return /^[A-Za-z0-9_-]{11}$/.test(String(videoId||''))?'https://www.youtube.com/watch?v='+videoId:''}
function thumbnailCandidates(videoId){
  const id=String(videoId||'');
  if(!/^[A-Za-z0-9_-]{11}$/.test(id))return [];
  return [
    'https://i.ytimg.com/vi/'+id+'/maxresdefault.jpg',
    'https://i.ytimg.com/vi/'+id+'/sddefault.jpg',
    'https://i.ytimg.com/vi/'+id+'/hqdefault.jpg',
    'https://i.ytimg.com/vi/'+id+'/mqdefault.jpg'
  ];
}
function thumbnailUrl(videoId){return thumbnailCandidates(videoId)[0]||''}
function thumbnailImage(videoId,{loading='lazy'}={}){
  const candidates=thumbnailCandidates(videoId);
  if(!candidates.length)return null;
  const img=el('img');img.alt='';img.loading=loading;img.referrerPolicy='no-referrer';
  let index=0;
  const next=()=>{if(index<candidates.length)img.src=candidates[index++]};
  img.addEventListener('error',next);
  next();
  return img;
}
function publicTypeLabel(type){
  return {
    merch_and_event:'活動・周邊',
    concert:'演出',
    music:'音樂',
    outfit_reveal:'新衣裝',
    membership_and_schedule:'近期行程',
    collab_preview:'合作預告',
    sponsored_and_schedule:'工商・行程',
    sponsored_and_merch:'工商・商品'
  }[text(type)]||'近期資訊';
}
function streamReference(videoId,byId){
  const row=byId.get(videoId);
  const details=el('details','daily-stream-ref');
  const head=el('summary','daily-stream-ref-head');
  const thumb=thumbnailUrl(videoId);
  if(thumb){
    const img=thumbnailImage(videoId);
    if(img)head.append(img);
  }
  const copy=el('span','daily-stream-ref-copy');
  copy.append(el('strong','',publicText(row?.channel_name)||'直播'));
  copy.append(el('span','',clampText(row?.title||'直播資訊',62)));
  head.append(copy);
  details.append(head);

  const body=el('div','daily-stream-ref-detail');
  const summary=publicText(row?.summary);
  if(summary)body.append(el('p','',summary));
  const topics=Array.isArray(row?.topics)?row.topics.map(publicText).filter(Boolean).slice(0,4):[];
  if(topics.length){
    const chips=el('div','daily-stream-topic-chips');
    topics.forEach(topic=>chips.append(el('span','',topic)));
    body.append(chips);
  }
  const href=text(row?.youtube_url)||youtubeUrl(videoId);
  if(href){
    const link=el('a','daily-stream-youtube','在 YouTube 開啟 ↗');
    link.href=href;link.target='_blank';link.rel='noopener noreferrer';body.append(link);
  }
  details.append(body);
  return details;
}
function storyVisibleIds(videoIds,byId){
  return [...new Set((Array.isArray(videoIds)?videoIds:[]).map(String).filter(id=>byId.has(id)))].slice(0,9);
}
function storyDetailRail(ids,byId){
  const visible=storyVisibleIds(ids,byId);
  if(!visible.length)return null;

  const shell=el('div','daily-story-detail-shell');
  if(visible.length<=2)shell.classList.add('is-small-set');
  const rail=el('div','daily-story-detail-rail');
  rail.dataset.openState='closed';

  const setGroupOpen=(open)=>{
    rail.dataset.openState=open?'open':'closed';
    rail.querySelectorAll('.daily-stream-ref').forEach(node=>{node.open=open});
  };

  visible.forEach((id,index)=>{
    const card=streamReference(id,byId);
    card.dataset.videoId=id;
    card.dataset.index=String(index);
    if(index===0)card.classList.add('is-selected');
    const summary=card.querySelector('summary');
    if(summary){
      summary.addEventListener('click',event=>{
        event.preventDefault();
        setGroupOpen(rail.dataset.openState!=='open');
      });
    }
    rail.append(card);
  });

  const controls=el('div','daily-story-detail-controls');
  const prev=el('button','daily-story-detail-arrow','←');
  const next=el('button','daily-story-detail-arrow','→');
  prev.type='button';next.type='button';
  prev.setAttribute('aria-label','上一組直播卡片');
  next.setAttribute('aria-label','下一組直播卡片');

  const step=()=>Math.max(rail.clientWidth*0.92,300);
  prev.addEventListener('click',()=>rail.scrollBy({left:-step(),behavior:'smooth'}));
  next.addEventListener('click',()=>rail.scrollBy({left:step(),behavior:'smooth'}));
  controls.append(prev,next);

  rail.selectVideo=(id,{open=false}={})=>{
    const target=rail.querySelector('.daily-stream-ref[data-video-id="'+CSS.escape(String(id))+'"]');
    if(!target)return;
    rail.querySelectorAll('.daily-stream-ref').forEach(node=>node.classList.toggle('is-selected',node===target));
    if(open)setGroupOpen(true);
    target.scrollIntoView({behavior:'smooth',block:'nearest',inline:'start'});
  };

  shell.append(rail,controls);
  shell.rail=rail;
  shell.selectVideo=(id,options)=>rail.selectVideo(id,options);
  shell.setGroupOpen=setGroupOpen;
  return shell;
}
function appendReferences(parent,ids,byId,{label='相關直播'}={}){
  const valid=[...new Set((Array.isArray(ids)?ids:[]).map(String).filter(id=>byId.has(id)))];
  if(!valid.length)return;
  const drawer=el('details','daily-source-drawer');
  drawer.append(el('summary','daily-source-drawer-label',label+' '+valid.length+' 場'));
  const refs=el('div','daily-stream-refs');
  valid.forEach(id=>refs.append(streamReference(id,byId)));
  drawer.append(refs);
  parent.append(drawer);
}
function section(title,className='',layout=''){
  const wrap=el('section','daily-v1-section'+(className?' '+className:''));
  if(layout)wrap.dataset.layout=layout;
  wrap.append(el('h2','daily-v1-section-title',title));
  return wrap;
}
function renderCoverage(target,artifact){
  const total=Number(artifact?.coverage?.total_streams||0);
  if(!total)return;
  const bar=el('div','daily-coverage daily-public-coverage');
  bar.append(el('span','daily-coverage-label','本日收錄'));
  bar.append(el('strong','',String(total)+' 場直播'));
  target.append(bar);
}
function overviewLayoutLabEnabled(){
  return new URLSearchParams(location.search).get('layoutlab')==='1';
}
function overviewHighlightModel(item){
  if(item&&typeof item==='object'&&!Array.isArray(item)){
    return {
      title:publicText(item.short_title||item.title),
      summary:publicText(item.summary||item.public_summary),
      videoIds:Array.isArray(item.video_ids)?item.video_ids.map(text).filter(Boolean):[]
    };
  }
  const raw=publicText(item);
  const parts=raw.split(/[：:]/);
  return {
    title:publicText(parts[0]||raw),
    summary:publicText(parts.length>1?parts.slice(1).join('：'):raw),
    videoIds:[]
  };
}
function overviewCardTitle(item){
  return overviewHighlightModel(item).title;
}
function applyArtifactOverviewLayout(grid,layout,highlights){
  applyOverviewLayout(grid,layout,highlights);
  // Keep the frozen Auto-Fit CSS path while recording that layout authority came from the artifact.
  grid.dataset.layoutSource='auto';
  grid.dataset.layoutAuthority='artifact';
}
function overviewAutoLayout(highlights){
  const lengths=highlights.slice(0,5).map(item=>overviewCardTitle(item).length);
  const first=lengths[0]||0;
  const max=Math.max(0,...lengths);
  const average=lengths.length?lengths.reduce((sum,n)=>sum+n,0)/lengths.length:0;
  const longCount=lengths.filter(length=>length>32).length;
  if(first>34||max>46)return 'lead';
  if(longCount>=2||average>29)return 'rail';
  return 'compact';
}
function applyOverviewLayout(grid,mode,highlights){
  const resolved=mode==='auto'?overviewAutoLayout(highlights):mode;
  grid.dataset.layout=resolved;
  grid.dataset.layoutSource=mode==='auto'?'auto':'manual';
  grid.querySelectorAll('.daily-highlight-card').forEach((card,index)=>{
    card.dataset.titleLength=String(overviewCardTitle(highlights[index]||'').length);
  });
}
function restoreOverviewFlow(flow){
  if(!flow)return;
  const original=flow.dataset.originalText||[...flow.querySelectorAll('.daily-overview-summary')].map(node=>publicText(node.textContent)).join('');
  if(!original)return;
  flow.dataset.originalText=original;
  flow.replaceChildren();
  appendParagraphs(flow,original,'daily-overview-summary');
}
function applyOverviewCopyLayout(wrap,mode){
  wrap.dataset.copyLayout=mode;
  const flow=wrap.querySelector('.daily-overview-summary-flow');
  if(!flow)return;
  restoreOverviewFlow(flow);
}
function overviewLayoutLab(wrap,grid,highlights){
  if(!overviewLayoutLabEnabled())return null;
  const lab=el('div','daily-layout-lab');
  const cardGroup=el('div','daily-layout-lab-group');
  cardGroup.append(el('span','daily-layout-lab-label','CARD'));
  const modes=[
    ['auto','Auto Fit'],
    ['compact','Compact Grid'],
    ['rail','Wide Rail'],
    ['lead','Lead + Grid']
  ];
  modes.forEach(([mode,label],index)=>{
    const button=el('button','daily-layout-lab-tab',label);
    button.type='button';
    button.dataset.layout=mode;
    if(index===0)button.classList.add('is-active');
    button.addEventListener('click',()=>{
      cardGroup.querySelectorAll('.daily-layout-lab-tab').forEach(node=>node.classList.toggle('is-active',node===button));
      applyOverviewLayout(grid,mode,highlights);
    });
    cardGroup.append(button);
  });

  const copyGroup=el('div','daily-layout-lab-group');
  copyGroup.append(el('span','daily-layout-lab-label','INTRO'));
  const copyModes=[
    ['left','Left'],
    ['center','Center'],
    ['right','Right'],
    ['columns','Two-column']
  ];
  copyModes.forEach(([mode,label],index)=>{
    const button=el('button','daily-layout-lab-tab',label);
    button.type='button';
    button.dataset.copyLayout=mode;
    if(index===0)button.classList.add('is-active');
    button.addEventListener('click',()=>{
      copyGroup.querySelectorAll('.daily-layout-lab-tab').forEach(node=>node.classList.toggle('is-active',node===button));
      applyOverviewCopyLayout(wrap,mode);
    });
    copyGroup.append(button);
  });

  lab.append(cardGroup,copyGroup);
  return lab;
}
function renderOverview(target,artifact,byId){
  const overview=artifact?.overview||{};
  const highlights=Array.isArray(overview.highlights)?overview.highlights.map(overviewHighlightModel).filter(item=>item.title||item.summary):[];
  if(!highlights.length&&!publicText(overview.public_summary||overview.summary))return;
  const wrap=section('今天發生什麼','daily-overview','brief');
  applyOverviewCopyLayout(wrap,'left');
  const intro=publicText(overview.public_summary||overview.summary);
  if(intro){
    const cleaned=intro.replace(/^.*?共計\s*\d+\s*場[^。]*。\s*/,'');
    if(cleaned){
      const introFlow=el('div','daily-overview-summary-flow');
      appendParagraphs(introFlow,cleaned,'daily-overview-summary');
      wrap.append(introFlow);
    }
  }
  if(highlights.length){
    const stories=Array.isArray(artifact?.stories)?artifact.stories:[];
    const grid=el('div','daily-highlight-grid');
    highlights.slice(0,5).forEach((item,index)=>{
      const card=el('article','daily-highlight-card');
      card.dataset.accent=String((index%3)+1);
      const story=stories[index];
      const firstVideo=[...(item.videoIds||[]),...(Array.isArray(story?.video_ids)?story.video_ids:[])]
        .map(String).find(id=>byId.has(id));
      if(firstVideo){
        const media=el('div','daily-highlight-media');
        const img=thumbnailImage(firstVideo,{loading:index===0?'eager':'lazy'});
        if(img)media.append(img);
        const row=byId.get(firstVideo),name=publicText(row?.channel_name);
        if(name)media.append(el('span','daily-highlight-channel',name));
        card.append(media);
      }
      const copy=el('div','daily-highlight-copy');
      const rawTitle=publicText(item.title);
      copy.append(el('h3','',shortHeadline(rawTitle,64)));
      copy.append(el('p','',clampText(item.summary,170)));
      card.append(copy);
      if(story){
        const targetId='daily-story-'+String(index+1);
        card.classList.add('is-jumpable');
        card.tabIndex=0;
        card.setAttribute('role','link');
        card.setAttribute('aria-label','前往詳細主題：'+rawTitle);
        const jump=()=>{
          const target=document.getElementById(targetId);
          if(target){
            history.replaceState(null,'','#'+targetId);
            target.scrollIntoView({behavior:'smooth',block:'start'});
          }
        };
        card.addEventListener('click',event=>{
          if(event.target.closest('a,button,summary,details'))return;
          jump();
        });
        card.addEventListener('keydown',event=>{
          if(event.key==='Enter'||event.key===' '){
            event.preventDefault();
            jump();
          }
        });
      }
      grid.append(card);
    });
    const artifactLayout=text(artifact?.overview_layout).toLowerCase();
    if(OVERVIEW_LAYOUTS.has(artifactLayout)){
      applyArtifactOverviewLayout(grid,artifactLayout,highlights);
    }else{
      applyOverviewLayout(grid,'auto',highlights);
      grid.dataset.layoutAuthority='legacy-auto';
    }
    const lab=overviewLayoutLab(wrap,grid,highlights);
    if(lab)wrap.append(lab);
    wrap.append(grid);
  }
  target.append(wrap);
}
function storyAutoLayout(story){
  return publicLayout(story,'editorial');
}
function singleImageStoryVariant(story,ordinal){
  const requested=publicText(story?.single_image_layout).toLowerCase();
  if(requested==='editorial-side'||requested==='wide')return requested;
  return ordinal%2===0?'editorial-side':'wide';
}
function renderStories(target,artifact,byId){
  const stories=Array.isArray(artifact?.stories)?artifact.stories:[];
  if(!stories.length)return;
  const wrap=section('今日主題','daily-stories','editorial');
  const list=el('div','daily-story-list');
  let singleImageOrdinal=0;
  let largeVisualOrdinal=0;
  stories.forEach((story,index)=>{
    const layout=storyAutoLayout(story);
    const card=el('article','daily-story-card');
    card.dataset.layout=layout;
    card.id='daily-story-'+String(index+1);
    const visibleIds=storyVisibleIds(story.video_ids,byId);
    card.dataset.streamCount=String(visibleIds.length);
    if(visibleIds.length===1){
      const variant=singleImageStoryVariant(story,singleImageOrdinal++);
      card.dataset.singleImageLayout=variant;
      if(variant==='editorial-side')card.classList.add('is-feature-story');
    }
    const eyebrow=el('div','daily-story-eyebrow');
    const members=Array.isArray(story.member_names)?story.member_names.map(publicText).filter(Boolean):[];
    eyebrow.append(el('span','',index===0?'今日焦點':'今日話題'));
    if(members.length)eyebrow.append(el('span','',members.slice(0,3).join('・')+(members.length>3?' 等':'')));
    card.append(eyebrow);

    const headline=publicText(story.title)||publicText(story.short_title);
    if(headline)card.append(el('h3','daily-story-title',headline));

    const summary=publicText(story.editorial_summary||story.public_summary||story.summary);
    if(summary){
      const copy=el('div','daily-story-summary-block');
      appendStoryEditorialCopy(copy,summary);
      card.append(copy);
    }
    const requestedReaderMode=publicText(story.reader_mode)==='inline'?'inline':'summary_with_details';
    const hasEditorialSummary=Boolean(publicText(story.editorial_summary));
    const readerMode=(visibleIds.length<=2&&hasEditorialSummary)?'inline':requestedReaderMode;
    card.dataset.readerMode=readerMode;
    const detailRail=readerMode==='summary_with_details'?storyDetailRail(story.video_ids,byId):null;
    const largeOrdinal=visibleIds.length>=6?largeVisualOrdinal++:0;
    const visualLayout=storyVisualLayout(visibleIds.length,{
      largeOrdinal,
      explicit:story.visual_layout
    });
    const visual=storyVisual(story.video_ids,byId,{
      layout:visualLayout,
      onSelect:(videoId)=>{
        if(detailRail)detailRail.selectVideo(videoId,{open:true});
      }
    });
    if(visual)card.append(visual);
    if(detailRail)card.append(detailRail);
    const allIds=[...new Set((Array.isArray(story.video_ids)?story.video_ids:[]).map(String).filter(id=>byId.has(id)))];
    if(allIds.length>9)appendReferences(card,allIds.slice(9),byId,{label:'更多相關直播'});
    list.append(card);
  });
  wrap.append(list);target.append(wrap);
}
function renderAnnouncements(target,artifact,byId){
  const rows=Array.isArray(artifact?.announcements)?artifact.announcements:[];
  if(!rows.length)return;
  const wrap=section('接下來值得注意','daily-announcements','timeline');
  const timeline=el('div','daily-announcement-timeline');
  rows.forEach(row=>{
    const card=el('article','daily-announcement-card');
    const when=el('div','daily-announcement-when');
    when.append(el('span','daily-announcement-type',publicTypeLabel(row.type)));
    if(publicText(row.event_date_text))when.append(el('time','',publicText(row.event_date_text)));
    card.append(when);
    if(publicText(row.title))card.append(el('h3','',publicText(row.title)));
    if(publicText(row.summary))card.append(el('p','',publicText(row.summary)));
    appendReferences(card,row.video_ids,byId,{label:'來源直播'});
    timeline.append(card);
  });
  wrap.append(timeline);target.append(wrap);
}
function renderCategories(target,artifact,byId){
  const rows=(Array.isArray(artifact?.categories)?artifact.categories:[])
    .filter(row=>text(row?.key)!=='unverified_streams');
  if(!rows.length)return;
  const wrap=section('依內容瀏覽','daily-categories','list');
  wrap.append(el('p','daily-category-intro','從主題切入，需要時再展開相關直播。'));
  const panels=el('div','daily-category-panels');

  rows.forEach((row,index)=>{
    const ids=[...new Set((Array.isArray(row.video_ids)?row.video_ids:[]).map(String).filter(id=>byId.has(id)))];
    if(!ids.length)return;

    const panel=el('details','daily-category');
    panel.id='daily-category-'+String(index);
    panel.append(el('summary','',publicText(row.label)||'分類'));

    const body=el('div','daily-category-body');
    const refs=el('div','daily-stream-refs daily-category-stream-refs');
    refs.dataset.openState='closed';

    const setGroupOpen=(open)=>{
      refs.dataset.openState=open?'open':'closed';
      refs.querySelectorAll('.daily-stream-ref').forEach(node=>{node.open=open});
    };

    ids.forEach(videoId=>{
      const card=streamReference(videoId,byId);
      const summary=card.querySelector('summary');
      if(summary){
        summary.addEventListener('click',event=>{
          event.preventDefault();
          setGroupOpen(refs.dataset.openState!=='open');
        });
      }
      refs.append(card);
    });

    const controls=el('div','daily-category-controls');
    const prev=el('button','daily-category-arrow','←');
    const next=el('button','daily-category-arrow','→');
    prev.type='button';next.type='button';
    prev.setAttribute('aria-label','上一組分類直播卡片');
    next.setAttribute('aria-label','下一組分類直播卡片');
    const step=()=>Math.max(refs.clientWidth*.92,300);
    prev.addEventListener('click',()=>refs.scrollBy({left:-step(),behavior:'smooth'}));
    next.addEventListener('click',()=>refs.scrollBy({left:step(),behavior:'smooth'}));
    controls.append(prev,next);

    body.append(refs,controls);
    panel.append(body);
    panels.append(panel);
  });

  wrap.append(panels);
  target.append(wrap);
}
function renderUnverified(target,artifact,byId){
  const debug=new URLSearchParams(location.search).get('debug')==='1';
  if(!debug)return;
  const rows=Array.isArray(artifact?.unverified)?artifact.unverified:[];
  if(!rows.length)return;
  const wrap=section('內部檢查：未驗證項目','daily-unverified','compact');
  wrap.append(el('p','daily-unverified-note','僅在 ?debug=1 顯示；Public 預設不呈現未驗證內容。'));
  rows.forEach(row=>{
    const item=el('article','daily-unverified-item'),stream=byId.get(String(row.video_id||''));
    item.append(el('strong','',publicText(stream?.channel_name)||'未驗證直播'));
    if(publicText(stream?.title))item.append(el('span','',publicText(stream.title)));
    if(publicText(row.reason))item.append(el('p','',publicText(row.reason)));
    wrap.append(item);
  });
  target.append(wrap);
}
function renderArtifact(target,artifact){
  target.replaceChildren();
  const byId=streamMap(artifact);
  renderCoverage(target,artifact);
  renderOverview(target,artifact,byId);
  renderStories(target,artifact,byId);
  renderAnnouncements(target,artifact,byId);
  renderCategories(target,artifact,byId);
  renderUnverified(target,artifact,byId);
  return target.childElementCount>0;
}

async function fetchArtifact(day){
  const url=artifactUrl(day);
  if(!url)return {state:'MISSING',artifact:null,reason:'unconfigured'};
  let response;
  const localPreview=location.hostname==='localhost'||location.hostname==='127.0.0.1';
  const monthlyShard=text(config().pathTemplate).includes('{month}');
  try{response=await fetch(url,{credentials:'omit',cache:(localPreview||monthlyShard||day===taipeiDay())?'no-cache':'force-cache'})}
  catch{return {state:'ERROR',artifact:null,reason:'network'}}
  if(response.status===404)return {state:'MISSING',artifact:null,reason:'not_found'};
  if(!response.ok)return {state:'ERROR',artifact:null,reason:'http_'+response.status};
  let payload;
  try{payload=await response.json()}catch{return {state:'ERROR',artifact:null,reason:'invalid_json'}}
  let artifact=payload;
  if(payload?.kind==='holodocchi.daily_digest_month'){
    const month=day.slice(0,7);
    if(payload.schema_version!==1||text(payload.month)!==month||!payload.days||typeof payload.days!=='object'){
      return {state:'ERROR',artifact:null,reason:'month_schema'};
    }
    artifact=payload.days[day]||null;
    if(!artifact)return {state:'MISSING',artifact:null,reason:'day_not_in_month'};
  }
  if(!artifact||artifact.schema_version!==SCHEMA_VERSION||artifact.kind!==KIND)return {state:'ERROR',artifact:null,reason:'schema'};
  if(text(artifact.target_day)!==day||artifact.timezone!==TAIPEI)return {state:'ERROR',artifact:null,reason:'day_mismatch'};
  return {state:artifact?.coverage?.complete===true?'READY':'PARTIAL',artifact,reason:''};
}
function setStatus(node,message,kind=''){if(!node)return;node.textContent=message;node.dataset.state=kind;node.hidden=!message}
function selectedDay(){const query=new URLSearchParams(location.search).get('date')||'';return DATE_RE.test(query)?query:taipeiDay()}
function setDailyUrl(day){const url=new URL(location.href);url.searchParams.set('date',day);location.href=url.pathname+url.search}
function monthKey(day){return DATE_RE.test(day)?day.slice(0,7):taipeiDay().slice(0,7)}
function shiftMonth(key,delta){const [year,month]=key.split('-').map(Number);const date=new Date(Date.UTC(year,month-1+delta,1,12));return date.getUTCFullYear()+'-'+String(date.getUTCMonth()+1).padStart(2,'0')}
function monthLabel(key){const [year,month]=key.split('-').map(Number);return new Intl.DateTimeFormat('zh-TW',{timeZone:'UTC',year:'numeric',month:'long'}).format(new Date(Date.UTC(year,month-1,1,12)))}
function initDailyDateHub(day,today){
  const dialog=document.getElementById('dailyDigestDateHub'),trigger=document.getElementById('dailyDigestDateTrigger'),grid=document.getElementById('dailyDigestDateGrid'),label=document.getElementById('dailyDigestMonthLabel'),prev=document.getElementById('dailyDigestMonthPrev'),next=document.getElementById('dailyDigestMonthNext'),todayButton=document.getElementById('dailyDigestDateToday'),close=document.getElementById('dailyDigestDateClose');
  if(!dialog||!trigger||!grid||!label)return;
  let month=monthKey(day);trigger.textContent=displayDay(day);
  function render(){
    label.textContent=monthLabel(month);grid.replaceChildren();
    const [year,monthNumber]=month.split('-').map(Number),first=new Date(Date.UTC(year,monthNumber-1,1,12)),start=first.getUTCDay(),days=new Date(Date.UTC(year,monthNumber,0,12)).getUTCDate();
    for(let slot=0;slot<42;slot++){
      const number=slot-start+1;
      if(number<1||number>days){grid.append(el('span','daily-date-hub-day is-empty'));continue}
      const value=month+'-'+String(number).padStart(2,'0'),button=el('button','daily-date-hub-day');
      button.type='button';button.append(el('strong','daily-date-hub-day-number',number));
      if(value===day)button.classList.add('is-selected');
      if(value===today)button.classList.add('is-today');
      if(value>today){button.disabled=true;button.classList.add('is-future')}else button.addEventListener('click',()=>setDailyUrl(value));
      grid.append(button);
    }
    next.disabled=month>=monthKey(today);
  }
  trigger.addEventListener('click',()=>{month=monthKey(day);render();dialog.showModal()});
  prev.addEventListener('click',()=>{month=shiftMonth(month,-1);render()});
  next.addEventListener('click',()=>{if(month<monthKey(today)){month=shiftMonth(month,1);render()}});
  todayButton.addEventListener('click',()=>setDailyUrl(today));
  close.addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close()});
}
async function initDaily(){
  const root=document.getElementById('daily-digest-page');if(!root)return;
  const content=document.getElementById('daily-digest-content'),status=document.getElementById('daily-digest-status'),title=document.getElementById('daily-digest-date-label');
  const day=selectedDay(),today=taipeiDay();
  if(title)title.textContent=displayDay(day)+' 日報';
  initDailyDateHub(day,today);
  setStatus(status,'正在載入日報…','loading');content.replaceChildren();
  const result=await fetchArtifact(day);
  if(result.state==='READY'||result.state==='PARTIAL'){
    const rendered=renderArtifact(content,result.artifact);
    if(rendered)setStatus(status,result.state==='PARTIAL'?'本日資料尚未完整，未驗證項目不會視為已驗證內容。':'',result.state);
    else setStatus(status,'本日 Daily Digest 沒有可顯示內容。',result.state);
  }else if(result.state==='MISSING')setStatus(status,displayDay(day)+' 日報尚未產生','MISSING');
  else setStatus(status,'日報暫時無法載入','ERROR');
}
window.HOLOVIEWER_DAILY_DIGEST=Object.freeze({schemaVersion:SCHEMA_VERSION,kind:KIND,taipeiDay,fetchArtifact,renderArtifact});
if(typeof document!=='undefined')document.addEventListener('DOMContentLoaded',initDaily,{once:true});
})();