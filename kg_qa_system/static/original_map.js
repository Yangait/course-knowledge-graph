/* Original artwork stays in an image; transparent controls supply interaction. */
window.OriginalMindmap = class {
    constructor(viewport, canvas, onSelect, onScale) {
        this.viewport = viewport; this.canvas = canvas;
        this.onSelect = onSelect; this.onScale = onScale;
        this.data = null; this.scale = 1; this.buttons = new Map(); this.drag = null;
        viewport.addEventListener('pointerdown', e => {
            if (!this.data || e.button !== 0) return;
            this.suppressClick=false;
            this.drag = {id:e.pointerId,x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop,moved:false};
        });
        viewport.addEventListener('pointermove', e => {
            const d = this.drag;
            if (!d || e.pointerId !== d.id) return;
            if (Math.hypot(e.clientX-d.x,e.clientY-d.y)>5) {
                d.moved=true; viewport.setPointerCapture(e.pointerId); viewport.classList.add('dragging');
            }
            if(d.moved) {viewport.scrollLeft=d.left-(e.clientX-d.x);viewport.scrollTop=d.top-(e.clientY-d.y);}
        });
        const stop = e => {
            if(!this.drag || this.drag.id!==e.pointerId)return;
            this.suppressClick=this.drag.moved;
            this.drag=null;viewport.classList.remove('dragging');
            if(viewport.hasPointerCapture(e.pointerId))viewport.releasePointerCapture(e.pointerId);
        };
        viewport.addEventListener('pointerup',stop);viewport.addEventListener('pointercancel',stop);
        viewport.addEventListener('click',e=>{
            if(this.suppressClick){e.stopImmediatePropagation();e.preventDefault();this.suppressClick=false;}
        },true);
        viewport.addEventListener('wheel',e=>{
            if(!this.data || !(e.ctrlKey || e.metaKey))return;
            e.preventDefault();const rect=viewport.getBoundingClientRect();
            this.zoom(this.scale*Math.exp(-e.deltaY*.002),e.clientX-rect.left,e.clientY-rect.top);
        },{passive:false});
    }
    clear() {
        this.data=null;this.buttons.clear();this.drag=null;this.suppressClick=false;
        this.scale=1;
        this.viewport.classList.remove('original-viewport','dragging');
    }
    mount(data) {
        this.data=data;this.viewport.classList.add('original-viewport');this.canvas.replaceChildren();
        const layer=document.createElement('div');layer.className='original-layer';this.layer=layer;
        layer.style.width=`${data.width}px`;layer.style.height=`${data.height}px`;
        const image=document.createElement('img');image.src=data.url;image.alt=`${data.name || '课程'}原始知识导图`;image.draggable=false;
        image.width=data.width;image.height=data.height;layer.append(image);
        this.buttons.clear();
        data.hotspots.forEach(h=>{
            const b=document.createElement('button');b.className='original-hotspot';b.dataset.node=h.id;
            b.setAttribute('aria-label',h.label);b.title=h.label;
            Object.assign(b.style,{left:`${h.x}px`,top:`${h.y}px`,width:`${h.width}px`,height:`${h.height}px`});
            b.onclick=()=>this.onSelect(h.id,false);
            b.onfocus=()=>{if(b.matches(':focus-visible'))this.focus(h.id);};
            layer.append(b);this.buttons.set(h.id,b);
        });this.canvas.append(layer);this.resize();
    }
    resize() {
        if(!this.data)return;
        this.layer.style.transform=`scale(${this.scale})`;
        this.canvas.style.width=`${this.data.width*this.scale}px`;
        this.canvas.style.height=`${this.data.height*this.scale}px`;
        this.onScale(this.scale);
    }
    zoom(scale,x=this.viewport.clientWidth/2,y=this.viewport.clientHeight/2) {
        if(!this.data)return;
        const px=(this.viewport.scrollLeft+x)/this.scale,py=(this.viewport.scrollTop+y)/this.scale;
        this.scale=Math.max(.001,Math.min(3,scale));this.resize();
        this.viewport.scrollLeft=px*this.scale-x;this.viewport.scrollTop=py*this.scale-y;
    }
    fit() {
        if(!this.data)return;
        this.scale=Math.min((this.viewport.clientWidth-20)/this.data.width,(this.viewport.clientHeight-20)/this.data.height,1);
        this.resize();this.viewport.scrollTo(0,0);
    }
    select(id) {
        this.buttons.forEach((b,key)=>{b.classList.toggle('selected',key===id);b.setAttribute('aria-pressed',String(key===id));});
    }
    focus(id) {
        const h=this.data?.hotspots.find(n=>n.id===id);if(!h)return;
        if(this.scale<.7){this.scale=1;this.resize();}
        this.viewport.scrollTo({left:(h.x+h.width/2)*this.scale-this.viewport.clientWidth/2,
            top:(h.y+h.height/2)*this.scale-this.viewport.clientHeight/2,behavior:'instant'});
    }
};
