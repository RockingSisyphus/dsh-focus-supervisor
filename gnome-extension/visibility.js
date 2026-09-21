// Rectangle visibility, matching the desktop metadata model (opaque windows).
// Transparent and irregular surfaces remain an approximation, not pixel clipping.
function subtract(rect,cover) {
    const [l,t,w,h]=rect;
    const x=Math.max(l,cover[0]),y=Math.max(t,cover[1]);
    const r=Math.min(l+w,cover[0]+cover[2]),b=Math.min(t+h,cover[1]+cover[3]);
    if(r<=x||b<=y)return [rect];
    return [[l,t,w,y-t],[l,b,w,t+h-b],[l,y,x-l,b-y],[r,y,l+w-r,b-y]].filter(v=>v[2]>0&&v[3]>0);
}
export function visibleIds(windows,screen) {
    const covers=[],visible=new Set();
    for(const window of [...windows].reverse()) {
        if(!window.mapped)continue;
        const [x,y,w,h]=window.rect;
        const l=Math.max(x,screen[0]),t=Math.max(y,screen[1]);
        let pieces=[[l,t,Math.min(x+w,screen[0]+screen[2])-l,Math.min(y+h,screen[1]+screen[3])-t]].filter(r=>r[2]>0&&r[3]>0);
        for(const cover of covers)pieces=pieces.flatMap(rect=>subtract(rect,cover));
        if(pieces.length)visible.add(window.id);
        covers.push(window.rect);
    }
    return visible;
}
