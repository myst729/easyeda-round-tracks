import argparse
from board import Board, floatToString
import math
from copy import copy
from collections import defaultdict
from line import Line, dist, add, sub, dot, intersect
import os

def subdivideTracks(tracks, radius = 0.5, radiusWidthMultiplier = 0.5, maxRadius = 3, 
                    minAngle = 360.0 / 64.0, minLength = 0.1, numIterations = 4):
    maxCosTheta = math.cos(math.radians(minAngle))
    for t in tracks:
        t.i = 0 # iteration number
    # perform mitxela's track subdivision smoothing algorithm                 
    for smoothpass in range(numIterations):
        #find all connected tracks
        intersections = defaultdict(list)
        for t in tracks:
            if t.length > 0:
                intersections[(t.start.x, t.start.y)].append(t)
                intersections[(t.end.x, t.end.y)].append(t)
        tracksToAdd = []
        for (x, y), tracksHere in intersections.items():
            if len(tracksHere) < 2:
                continue
            for t in tracksHere:
                if t.start.x != x or t.start.y != y:
                    # flip track such that all tracks start at the intersection point
                    t.reverse()
        
            #sort these tracks by angle, so new tracks can be drawn between them
            tracksHere.sort(key = Line.angle)

            #find the largest angle between two tracks
            cosAnglesBetweenTracks = []
            for t in range(len(tracksHere)):
                t0, t1 = tracksHere[t - 1], tracksHere[t]
                #skip pairs that won't be smoothed (see below)
                if smoothpass == 0 or t0.i != t1.i:
                    cosAnglesBetweenTracks.append(abs(dot(t0.dir, t1.dir)))
            #skip if tracks already smooth/straight enough
            if (len(cosAnglesBetweenTracks) == 0 or
                min(cosAnglesBetweenTracks) > maxCosTheta):
                continue
            
            #shorten all these tracks (push start points away from intersection point)
            shortestTrackLen = min(t.length for t in tracksHere)
            for t in range(len(tracksHere)):
                t0, t1 = tracksHere[t - 1], tracksHere[t]
                cosHalfTheta = math.sqrt(.5 * max(0, 1.0 - dot(t0.dir, t1.dir)))
                r = min(maxRadius, radius + radiusWidthMultiplier * t0.width, t0.length - minLength)
                amountToShorten = min(shortestTrackLen / (2 * cosHalfTheta + 2), r)
                if amountToShorten >= minLength:
                    t0.length -= amountToShorten
                    t0.start = t0.pointOnLine(amountToShorten)

            #connect the new start points in a circle around the old center point
            for t in range(len(tracksHere)):
                t0, t1 = tracksHere[t - 1], tracksHere[t]
                #don't add 2 new tracks in the 2 track case
                if len(tracksHere) > 2 or t == 1:
                    # don't link two tracks that were both generated by a previous pass
                    # to stop 3+ way junctions going fractal
                    if smoothpass == 0 or t0.i != t1.i:
                        thinTrack = t0 if t0.width < t1.width else t1
                        tracksToAdd.append((copy(t0.start), copy(t1.start), thinTrack))

        #add all the new tracks in post, so as not to cause problems with set iteration
        for start, end, track in tracksToAdd:
            t = copy(track)
            t.start = start
            t.end = end
            t.i = smoothpass + 1
            if t.update():
                tracks.append(t)

def smoothMultiWayJunctions(tracks, board, radius = 0.5, radiusWidthMultiplier = 0.5, maxRadius = 3):
    # this is way too complicated and doesn't work brilliantly
    # to do: simply find intersections of track edges with angles <180 degrees and add arcs?
    tracks.sort(key = Line.GetWidth, reverse = True)
    processedPoints = set()
    for i, track in enumerate(tracks):
        w = track.width
        for p in (track.start, track.end):
            if (p.x, p.y) in processedPoints:
                continue
            p = copy(p)
            if p.x != track.start.x or p.y != track.start.y:
                track.reverse()
            tracksHere = [track]
            for t2 in tracks:
                if t2 == track:
                    continue
                d = dist(t2.start, p)
                d2 = dist(t2.end, p)
                if d2 < d:
                    d = d2
                    t2.reverse()
                if d < (w + t2.width) * .5:
                    for i, t3 in enumerate(tracksHere):
                        # if an existing track in tracksHere is attached to the
                        # end of the candidate track t2 then it is not the closest
                        # part of that track to the junction point so remove it
                        if t3.start.x == t2.end.x and t3.start.y == t2.end.y:
                            tracksHere.pop(i)
                            break
                        # likewise, if our candidate track is attached to the
                        # end of an existing track it is a more distant part of an
                        # existing track and so should not be added
                        if t2.start.x == t3.end.x and t2.start.y == t3.end.y:
                            t2 = None
                            break
                    if t2:
                        tracksHere.append(t2)
            if len(tracksHere) < 3: #2:
                continue
            equalPositions = True
            equalWidths = True
            for t in tracksHere:
                if t.width != track.width:
                    equalWidths = False
                    break
                if t.start.x != p.x or t.start.y != p.y:
                    equalPositions = False
                    break
            if equalWidths and equalPositions: # and len(tracksHere) < 3:
                # use the subdivision algorithm if all the tracks are
                # of equal width and intersect at one point 
                continue
            
            spline = ''
            tracksHere.sort(key = Line.angle)
            shortestTrackLen = min(t.length for t in tracksHere)
            shortenAmount = [float("inf")] * len(tracksHere)
            splineSegs = 0
            for t in range(len(tracksHere)):
                t0, t1 = tracksHere[t - 1], tracksHere[t]
                w = min(t0.width, t1.width)
                edge0, edge1 = copy(t0), copy(t1)
                # take right edge of t0 
                edge0.start = add(t0.start, t0.vecToEdge(t0.width - w))
                edge0.end   = add(t0.end,   t0.vecToEdge(t0.width - w))
                # and left edge of t1 
                edge1.start = sub(t1.start, t1.vecToEdge(t1.width - w))
                edge1.end   = sub(t1.end,   t1.vecToEdge(t1.width - w))

                # find the inside corner
                corner = intersect(edge0, edge1, bounded=False)
                if corner:
                    edge0.start = edge1.start = corner
                # desired radius
                r = 2 * min(maxRadius, radius + w * radiusWidthMultiplier)
                # clamp to ends of tracks
                r = min(r, edge0.projectedLength(t0.end), 
                           edge1.projectedLength(t1.end))
                # store the amount to shorten each track by
                if r <= 0.0:
                    shortenAmount[t - 1] = shortenAmount[t] = 0.0
                    r = 0.0
                    l0 = l1 = 0.0
                    #spline += 'M' if not spline else 'L'
                    #spline += f' {edge0.start.x} {edge0.start.y} L {edge1.start.x} {edge1.start.y} '
                else:
                    l0 = t0.projectedLength(edge0.pointOnLine(r), bounded=False)
                    shortenAmount[t - 1] = min(shortenAmount[t - 1], l0)
                    l1 = t1.projectedLength(edge1.pointOnLine(r), bounded=False)
                    shortenAmount[t] = min(shortenAmount[t], l1)
                # generate arc
                p1 = edge0.pointOnLine(r)
                p2 = edge1.pointOnLine(r)
                #p0 = t0.closestPoint(p1)
                #spline += f' {p0.x} {p0.y} L '
                cos2t = .5 + .5 * dot(edge0.dir, edge1.dir)
                if (l0 > 0 and l0 <= t0.length and #+ t0.width * .5 and 
                    l1 > 0 and l1 <= t1.length ): #+ t1.width * .5): #corner and r > 0 and cos2t > 0.001:
                    #spline = f'M {corner.x} {corner.y} L'
                    spline += 'M' if not spline else 'L'
                    spline += f' {p1.x} {p1.y} '
                    if cos2t > 0.001:
                        r = math.sqrt(r * r * (1 - cos2t) / cos2t)
                        r = floatToString(round(r, 5))
                        spline += f'A {r} {r} 0 0 0 '
                    else:
                        spline += 'L '
                    spline += f'{p2.x} {p2.y} '
                    splineSegs += 1

                    if cos2t > 0.001 and cos2t < 0.999:
                        # blah, let's just add an arc using the thin track width
                        w = min(t0.width, t1.width) 
                        #p1 = Vector(p1.x + t0.dir.y * w * .5, p1.y - t0.dir.x * w * .5)
                        #p2 = Vector(p2.x - t1.dir.y * w * .5, p2.y + t1.dir.y * w * .5)
                        arc = f"ARC~{floatToString(w)}~{track.layer}~{track.net}~M "
                        arc += f"{floatToString(round(p1.x, 5))} "
                        arc += f"{floatToString(round(p1.y, 5))} "
                        #r = math.sqrt(r * r * (1 - cos2t) / cos2t)
                        #r = floatToString(round(r, 5))
                        arc += f"A {r} {r} 0 0 0 "
                        arc += f"{floatToString(round(p2.x, 5))} "
                        arc += f"{floatToString(round(p2.y, 5))} "
                        arc += f"~~{board.getShapeId()}~0"
                        board.addShape(arc)
                    else:
                        shortenAmount[t - 1] = shortenAmount[t] = 0.0

            if 0: #splineSegs > 1:
                spline += 'Z'
                board.addShape(f"SOLIDREGION~{track.layer}~{track.net}~{spline}~solid~{board.getShapeId()}~~~~0")

            # shorten the tracks
            for t, s in zip(tracksHere, shortenAmount):
                if s > 0.0 and s <= t.length:
                    #t.start = t.pointOnLine(s)
                    #t.length -= s
                    processedPoints.add((t.start.x, t.start.y))

def main():
    parser = argparse.ArgumentParser(description = "Round off the corners of copper tracks in an EasyEDA board json file")
    parser.add_argument('filename', help="input file")
    parser.add_argument('outputfile', help="outfile file", nargs="?")
    parser.add_argument('--radius', help="Radius to round 90 degree corners to in mils", type=float, default=5.0)
    parser.add_argument('--radiusWidthMultiplier', help="Corner radius is expanded by the width of the track multiplied by this value", type=float, default=0.5)
    parser.add_argument('--maxRadius', help="Maximum corner radius (in mils)", type=float, default=30.0)
    parser.add_argument('--minAngle', help="Stop rounding when angle between two tracks is smaller than this", type=float, default=360.0/64.0)
    parser.add_argument('--minLength', help="Stop rounding when track segments are shorter than this (mils)", type=float, default=1.0)
    parser.add_argument('--iterations', help="Number of passes to make over each track during smoothing", type=int, default=4)
    parser.add_argument('--multiway', help="Run multi-way junction arc generation algorithm ", type=bool, default=False)
    args = parser.parse_args()
    board = Board()
    board.load(args.filename)
    for tracks in board.tracksByNetAndLayer.values():
        if args.multiway:
            smoothMultiWayJunctions(tracks, board, args.radius * 0.1, args.radiusWidthMultiplier, args.maxRadius * 0.1)
        subdivideTracks(tracks, args.radius * 0.1, args.radiusWidthMultiplier, args.maxRadius * 0.1,
            args.minAngle, args.minLength * 0.1, args.iterations)
    outname = args.outputfile
    if not outname:
        name, ext = os.path.splitext(args.filename)
        outname = name + '_smoothed' + ext
    board.save(outname)

if __name__ == '__main__':
    main()