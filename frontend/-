// node_modules/d3-force-3d/src/center.js
function center_default(x3, y3, z3) {
  var nodes, strength = 1;
  if (x3 == null) x3 = 0;
  if (y3 == null) y3 = 0;
  if (z3 == null) z3 = 0;
  function force() {
    var i, n = nodes.length, node, sx = 0, sy = 0, sz = 0;
    for (i = 0; i < n; ++i) {
      node = nodes[i], sx += node.x || 0, sy += node.y || 0, sz += node.z || 0;
    }
    for (sx = (sx / n - x3) * strength, sy = (sy / n - y3) * strength, sz = (sz / n - z3) * strength, i = 0; i < n; ++i) {
      node = nodes[i];
      if (sx) {
        node.x -= sx;
      }
      if (sy) {
        node.y -= sy;
      }
      if (sz) {
        node.z -= sz;
      }
    }
  }
  force.initialize = function(_) {
    nodes = _;
  };
  force.x = function(_) {
    return arguments.length ? (x3 = +_, force) : x3;
  };
  force.y = function(_) {
    return arguments.length ? (y3 = +_, force) : y3;
  };
  force.z = function(_) {
    return arguments.length ? (z3 = +_, force) : z3;
  };
  force.strength = function(_) {
    return arguments.length ? (strength = +_, force) : strength;
  };
  return force;
}

// node_modules/d3-binarytree/src/add.js
function add_default(d) {
  const x3 = +this._x.call(null, d);
  return add(this.cover(x3), x3, d);
}
function add(tree, x3, d) {
  if (isNaN(x3)) return tree;
  var parent, node = tree._root, leaf = { data: d }, x0 = tree._x0, x1 = tree._x1, xm, xp, right, i, j;
  if (!node) return tree._root = leaf, tree;
  while (node.length) {
    if (right = x3 >= (xm = (x0 + x1) / 2)) x0 = xm;
    else x1 = xm;
    if (parent = node, !(node = node[i = +right])) return parent[i] = leaf, tree;
  }
  xp = +tree._x.call(null, node.data);
  if (x3 === xp) return leaf.next = node, parent ? parent[i] = leaf : tree._root = leaf, tree;
  do {
    parent = parent ? parent[i] = new Array(2) : tree._root = new Array(2);
    if (right = x3 >= (xm = (x0 + x1) / 2)) x0 = xm;
    else x1 = xm;
  } while ((i = +right) === (j = +(xp >= xm)));
  return parent[j] = node, parent[i] = leaf, tree;
}
function addAll(data) {
  if (!Array.isArray(data)) data = Array.from(data);
  const n = data.length;
  const xz = new Float64Array(n);
  let x0 = Infinity, x1 = -Infinity;
  for (let i = 0, x3; i < n; ++i) {
    if (isNaN(x3 = +this._x.call(null, data[i]))) continue;
    xz[i] = x3;
    if (x3 < x0) x0 = x3;
    if (x3 > x1) x1 = x3;
  }
  if (x0 > x1) return this;
  this.cover(x0).cover(x1);
  for (let i = 0; i < n; ++i) {
    add(this, xz[i], data[i]);
  }
  return this;
}

// node_modules/d3-binarytree/src/cover.js
function cover_default(x3) {
  if (isNaN(x3 = +x3)) return this;
  var x0 = this._x0, x1 = this._x1;
  if (isNaN(x0)) {
    x1 = (x0 = Math.floor(x3)) + 1;
  } else {
    var z3 = x1 - x0 || 1, node = this._root, parent, i;
    while (x0 > x3 || x3 >= x1) {
      i = +(x3 < x0);
      parent = new Array(2), parent[i] = node, node = parent, z3 *= 2;
      switch (i) {
        case 0:
          x1 = x0 + z3;
          break;
        case 1:
          x0 = x1 - z3;
          break;
      }
    }
    if (this._root && this._root.length) this._root = node;
  }
  this._x0 = x0;
  this._x1 = x1;
  return this;
}

// node_modules/d3-binarytree/src/data.js
function data_default() {
  var data = [];
  this.visit(function(node) {
    if (!node.length) do
      data.push(node.data);
    while (node = node.next);
  });
  return data;
}

// node_modules/d3-binarytree/src/extent.js
function extent_default(_) {
  return arguments.length ? this.cover(+_[0][0]).cover(+_[1][0]) : isNaN(this._x0) ? void 0 : [[this._x0], [this._x1]];
}

// node_modules/d3-binarytree/src/half.js
function half_default(node, x0, x1) {
  this.node = node;
  this.x0 = x0;
  this.x1 = x1;
}

// node_modules/d3-binarytree/src/find.js
function find_default(x3, radius) {
  var data, x0 = this._x0, x1, x22, x32 = this._x1, halves = [], node = this._root, q, i;
  if (node) halves.push(new half_default(node, x0, x32));
  if (radius == null) radius = Infinity;
  else {
    x0 = x3 - radius;
    x32 = x3 + radius;
  }
  while (q = halves.pop()) {
    if (!(node = q.node) || (x1 = q.x0) > x32 || (x22 = q.x1) < x0) continue;
    if (node.length) {
      var xm = (x1 + x22) / 2;
      halves.push(
        new half_default(node[1], xm, x22),
        new half_default(node[0], x1, xm)
      );
      if (i = +(x3 >= xm)) {
        q = halves[halves.length - 1];
        halves[halves.length - 1] = halves[halves.length - 1 - i];
        halves[halves.length - 1 - i] = q;
      }
    } else {
      var d = Math.abs(x3 - +this._x.call(null, node.data));
      if (d < radius) {
        radius = d;
        x0 = x3 - d;
        x32 = x3 + d;
        data = node.data;
      }
    }
  }
  return data;
}

// node_modules/d3-binarytree/src/remove.js
function remove_default(d) {
  if (isNaN(x3 = +this._x.call(null, d))) return this;
  var parent, node = this._root, retainer, previous, next, x0 = this._x0, x1 = this._x1, x3, xm, right, i, j;
  if (!node) return this;
  if (node.length) while (true) {
    if (right = x3 >= (xm = (x0 + x1) / 2)) x0 = xm;
    else x1 = xm;
    if (!(parent = node, node = node[i = +right])) return this;
    if (!node.length) break;
    if (parent[i + 1 & 1]) retainer = parent, j = i;
  }
  while (node.data !== d) if (!(previous = node, node = node.next)) return this;
  if (next = node.next) delete node.next;
  if (previous) return next ? previous.next = next : delete previous.next, this;
  if (!parent) return this._root = next, this;
  next ? parent[i] = next : delete parent[i];
  if ((node = parent[0] || parent[1]) && node === (parent[1] || parent[0]) && !node.length) {
    if (retainer) retainer[j] = node;
    else this._root = node;
  }
  return this;
}
function removeAll(data) {
  for (var i = 0, n = data.length; i < n; ++i) this.remove(data[i]);
  return this;
}

// node_modules/d3-binarytree/src/root.js
function root_default() {
  return this._root;
}

// node_modules/d3-binarytree/src/size.js
function size_default() {
  var size = 0;
  this.visit(function(node) {
    if (!node.length) do
      ++size;
    while (node = node.next);
  });
  return size;
}

// node_modules/d3-binarytree/src/visit.js
function visit_default(callback) {
  var halves = [], q, node = this._root, child, x0, x1;
  if (node) halves.push(new half_default(node, this._x0, this._x1));
  while (q = halves.pop()) {
    if (!callback(node = q.node, x0 = q.x0, x1 = q.x1) && node.length) {
      var xm = (x0 + x1) / 2;
      if (child = node[1]) halves.push(new half_default(child, xm, x1));
      if (child = node[0]) halves.push(new half_default(child, x0, xm));
    }
  }
  return this;
}

// node_modules/d3-binarytree/src/visitAfter.js
function visitAfter_default(callback) {
  var halves = [], next = [], q;
  if (this._root) halves.push(new half_default(this._root, this._x0, this._x1));
  while (q = halves.pop()) {
    var node = q.node;
    if (node.length) {
      var child, x0 = q.x0, x1 = q.x1, xm = (x0 + x1) / 2;
      if (child = node[0]) halves.push(new half_default(child, x0, xm));
      if (child = node[1]) halves.push(new half_default(child, xm, x1));
    }
    next.push(q);
  }
  while (q = next.pop()) {
    callback(q.node, q.x0, q.x1);
  }
  return this;
}

// node_modules/d3-binarytree/src/x.js
function defaultX(d) {
  return d[0];
}
function x_default(_) {
  return arguments.length ? (this._x = _, this) : this._x;
}

// node_modules/d3-binarytree/src/binarytree.js
function binarytree(nodes, x3) {
  var tree = new Binarytree(x3 == null ? defaultX : x3, NaN, NaN);
  return nodes == null ? tree : tree.addAll(nodes);
}
function Binarytree(x3, x0, x1) {
  this._x = x3;
  this._x0 = x0;
  this._x1 = x1;
  this._root = void 0;
}
function leaf_copy(leaf) {
  var copy = { data: leaf.data }, next = copy;
  while (leaf = leaf.next) next = next.next = { data: leaf.data };
  return copy;
}
var treeProto = binarytree.prototype = Binarytree.prototype;
treeProto.copy = function() {
  var copy = new Binarytree(this._x, this._x0, this._x1), node = this._root, nodes, child;
  if (!node) return copy;
  if (!node.length) return copy._root = leaf_copy(node), copy;
  nodes = [{ source: node, target: copy._root = new Array(2) }];
  while (node = nodes.pop()) {
    for (var i = 0; i < 2; ++i) {
      if (child = node.source[i]) {
        if (child.length) nodes.push({ source: child, target: node.target[i] = new Array(2) });
        else node.target[i] = leaf_copy(child);
      }
    }
  }
  return copy;
};
treeProto.add = add_default;
treeProto.addAll = addAll;
treeProto.cover = cover_default;
treeProto.data = data_default;
treeProto.extent = extent_default;
treeProto.find = find_default;
treeProto.remove = remove_default;
treeProto.removeAll = removeAll;
treeProto.root = root_default;
treeProto.size = size_default;
treeProto.visit = visit_default;
treeProto.visitAfter = visitAfter_default;
treeProto.x = x_default;

// node_modules/d3-force-3d/src/collide.js
import { quadtree } from "d3-quadtree";

// node_modules/d3-octree/src/add.js
function add_default2(d) {
  const x3 = +this._x.call(null, d), y3 = +this._y.call(null, d), z3 = +this._z.call(null, d);
  return add2(this.cover(x3, y3, z3), x3, y3, z3, d);
}
function add2(tree, x3, y3, z3, d) {
  if (isNaN(x3) || isNaN(y3) || isNaN(z3)) return tree;
  var parent, node = tree._root, leaf = { data: d }, x0 = tree._x0, y0 = tree._y0, z0 = tree._z0, x1 = tree._x1, y1 = tree._y1, z1 = tree._z1, xm, ym, zm, xp, yp, zp, right, bottom, deep, i, j;
  if (!node) return tree._root = leaf, tree;
  while (node.length) {
    if (right = x3 >= (xm = (x0 + x1) / 2)) x0 = xm;
    else x1 = xm;
    if (bottom = y3 >= (ym = (y0 + y1) / 2)) y0 = ym;
    else y1 = ym;
    if (deep = z3 >= (zm = (z0 + z1) / 2)) z0 = zm;
    else z1 = zm;
    if (parent = node, !(node = node[i = deep << 2 | bottom << 1 | right])) return parent[i] = leaf, tree;
  }
  xp = +tree._x.call(null, node.data);
  yp = +tree._y.call(null, node.data);
  zp = +tree._z.call(null, node.data);
  if (x3 === xp && y3 === yp && z3 === zp) return leaf.next = node, parent ? parent[i] = leaf : tree._root = leaf, tree;
  do {
    parent = parent ? parent[i] = new Array(8) : tree._root = new Array(8);
    if (right = x3 >= (xm = (x0 + x1) / 2)) x0 = xm;
    else x1 = xm;
    if (bottom = y3 >= (ym = (y0 + y1) / 2)) y0 = ym;
    else y1 = ym;
    if (deep = z3 >= (zm = (z0 + z1) / 2)) z0 = zm;
    else z1 = zm;
  } while ((i = deep << 2 | bottom << 1 | right) === (j = (zp >= zm) << 2 | (yp >= ym) << 1 | xp >= xm));
  return parent[j] = node, parent[i] = leaf, tree;
}
function addAll2(data) {
  if (!Array.isArray(data)) data = Array.from(data);
  const n = data.length;
  const xz = new Float64Array(n);
  const yz = new Float64Array(n);
  const zz = new Float64Array(n);
  let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity, y1 = -Infinity, z1 = -Infinity;
  for (let i = 0, d, x3, y3, z3; i < n; ++i) {
    if (isNaN(x3 = +this._x.call(null, d = data[i])) || isNaN(y3 = +this._y.call(null, d)) || isNaN(z3 = +this._z.call(null, d))) continue;
    xz[i] = x3;
    yz[i] = y3;
    zz[i] = z3;
    if (x3 < x0) x0 = x3;
    if (x3 > x1) x1 = x3;
    if (y3 < y0) y0 = y3;
    if (y3 > y1) y1 = y3;
    if (z3 < z0) z0 = z3;
    if (z3 > z1) z1 = z3;
  }
  if (x0 > x1 || y0 > y1 || z0 > z1) return this;
  this.cover(x0, y0, z0).cover(x1, y1, z1);
  for (let i = 0; i < n; ++i) {
    add2(this, xz[i], yz[i], zz[i], data[i]);
  }
  return this;
}

// node_modules/d3-octree/src/cover.js
function cover_default2(x3, y3, z3) {
  if (isNaN(x3 = +x3) || isNaN(y3 = +y3) || isNaN(z3 = +z3)) return this;
  var x0 = this._x0, y0 = this._y0, z0 = this._z0, x1 = this._x1, y1 = this._y1, z1 = this._z1;
  if (isNaN(x0)) {
    x1 = (x0 = Math.floor(x3)) + 1;
    y1 = (y0 = Math.floor(y3)) + 1;
    z1 = (z0 = Math.floor(z3)) + 1;
  } else {
    var t = x1 - x0 || 1, node = this._root, parent, i;
    while (x0 > x3 || x3 >= x1 || y0 > y3 || y3 >= y1 || z0 > z3 || z3 >= z1) {
      i = (z3 < z0) << 2 | (y3 < y0) << 1 | x3 < x0;
      parent = new Array(8), parent[i] = node, node = parent, t *= 2;
      switch (i) {
        case 0:
          x1 = x0 + t, y1 = y0 + t, z1 = z0 + t;
          break;
        case 1:
          x0 = x1 - t, y1 = y0 + t, z1 = z0 + t;
          break;
        case 2:
          x1 = x0 + t, y0 = y1 - t, z1 = z0 + t;
          break;
        case 3:
          x0 = x1 - t, y0 = y1 - t, z1 = z0 + t;
          break;
        case 4:
          x1 = x0 + t, y1 = y0 + t, z0 = z1 - t;
          break;
        case 5:
          x0 = x1 - t, y1 = y0 + t, z0 = z1 - t;
          break;
        case 6:
          x1 = x0 + t, y0 = y1 - t, z0 = z1 - t;
          break;
        case 7:
          x0 = x1 - t, y0 = y1 - t, z0 = z1 - t;
          break;
      }
    }
    if (this._root && this._root.length) this._root = node;
  }
  this._x0 = x0;
  this._y0 = y0;
  this._z0 = z0;
  this._x1 = x1;
  this._y1 = y1;
  this._z1 = z1;
  return this;
}

// node_modules/d3-octree/src/data.js
function data_default2() {
  var data = [];
  this.visit(function(node) {
    if (!node.length) do
      data.push(node.data);
    while (node = node.next);
  });
  return data;
}

// node_modules/d3-octree/src/extent.js
function extent_default2(_) {
  return arguments.length ? this.cover(+_[0][0], +_[0][1], +_[0][2]).cover(+_[1][0], +_[1][1], +_[1][2]) : isNaN(this._x0) ? void 0 : [[this._x0, this._y0, this._z0], [this._x1, this._y1, this._z1]];
}

// node_modules/d3-octree/src/octant.js
function octant_default(node, x0, y0, z0, x1, y1, z1) {
  this.node = node;
  this.x0 = x0;
  this.y0 = y0;
  this.z0 = z0;
  this.x1 = x1;
  this.y1 = y1;
  this.z1 = z1;
}

// node_modules/d3-octree/src/find.js
function find_default2(x3, y3, z3, radius) {
  var data, x0 = this._x0, y0 = this._y0, z0 = this._z0, x1, y1, z1, x22, y22, z22, x32 = this._x1, y32 = this._y1, z32 = this._z1, octs = [], node = this._root, q, i;
  if (node) octs.push(new octant_default(node, x0, y0, z0, x32, y32, z32));
  if (radius == null) radius = Infinity;
  else {
    x0 = x3 - radius, y0 = y3 - radius, z0 = z3 - radius;
    x32 = x3 + radius, y32 = y3 + radius, z32 = z3 + radius;
    radius *= radius;
  }
  while (q = octs.pop()) {
    if (!(node = q.node) || (x1 = q.x0) > x32 || (y1 = q.y0) > y32 || (z1 = q.z0) > z32 || (x22 = q.x1) < x0 || (y22 = q.y1) < y0 || (z22 = q.z1) < z0) continue;
    if (node.length) {
      var xm = (x1 + x22) / 2, ym = (y1 + y22) / 2, zm = (z1 + z22) / 2;
      octs.push(
        new octant_default(node[7], xm, ym, zm, x22, y22, z22),
        new octant_default(node[6], x1, ym, zm, xm, y22, z22),
        new octant_default(node[5], xm, y1, zm, x22, ym, z22),
        new octant_default(node[4], x1, y1, zm, xm, ym, z22),
        new octant_default(node[3], xm, ym, z1, x22, y22, zm),
        new octant_default(node[2], x1, ym, z1, xm, y22, zm),
        new octant_default(node[1], xm, y1, z1, x22, ym, zm),
        new octant_default(node[0], x1, y1, z1, xm, ym, zm)
      );
      if (i = (z3 >= zm) << 2 | (y3 >= ym) << 1 | x3 >= xm) {
        q = octs[octs.length - 1];
        octs[octs.length - 1] = octs[octs.length - 1 - i];
        octs[octs.length - 1 - i] = q;
      }
    } else {
      var dx = x3 - +this._x.call(null, node.data), dy = y3 - +this._y.call(null, node.data), dz = z3 - +this._z.call(null, node.data), d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < radius) {
        var d = Math.sqrt(radius = d2);
        x0 = x3 - d, y0 = y3 - d, z0 = z3 - d;
        x32 = x3 + d, y32 = y3 + d, z32 = z3 + d;
        data = node.data;
      }
    }
  }
  return data;
}

// node_modules/d3-octree/src/findAll.js
var distance = (x1, y1, z1, x22, y22, z22) => Math.sqrt((x1 - x22) ** 2 + (y1 - y22) ** 2 + (z1 - z22) ** 2);
function findAllWithinRadius(x3, y3, z3, radius) {
  const result = [];
  const xMin = x3 - radius;
  const yMin = y3 - radius;
  const zMin = z3 - radius;
  const xMax = x3 + radius;
  const yMax = y3 + radius;
  const zMax = z3 + radius;
  this.visit((node, x1, y1, z1, x22, y22, z22) => {
    if (!node.length) {
      do {
        const d = node.data;
        if (distance(x3, y3, z3, this._x(d), this._y(d), this._z(d)) <= radius) {
          result.push(d);
        }
      } while (node = node.next);
    }
    return x1 > xMax || y1 > yMax || z1 > zMax || x22 < xMin || y22 < yMin || z22 < zMin;
  });
  return result;
}

// node_modules/d3-octree/src/remove.js
function remove_default2(d) {
  if (isNaN(x3 = +this._x.call(null, d)) || isNaN(y3 = +this._y.call(null, d)) || isNaN(z3 = +this._z.call(null, d))) return this;
  var parent, node = this._root, retainer, previous, next, x0 = this._x0, y0 = this._y0, z0 = this._z0, x1 = this._x1, y1 = this._y1, z1 = this._z1, x3, y3, z3, xm, ym, zm, right, bottom, deep, i, j;
  if (!node) return this;
  if (node.length) while (true) {
    if (right = x3 >= (xm = (x0 + x1) / 2)) x0 = xm;
    else x1 = xm;
    if (bottom = y3 >= (ym = (y0 + y1) / 2)) y0 = ym;
    else y1 = ym;
    if (deep = z3 >= (zm = (z0 + z1) / 2)) z0 = zm;
    else z1 = zm;
    if (!(parent = node, node = node[i = deep << 2 | bottom << 1 | right])) return this;
    if (!node.length) break;
    if (parent[i + 1 & 7] || parent[i + 2 & 7] || parent[i + 3 & 7] || parent[i + 4 & 7] || parent[i + 5 & 7] || parent[i + 6 & 7] || parent[i + 7 & 7]) retainer = parent, j = i;
  }
  while (node.data !== d) if (!(previous = node, node = node.next)) return this;
  if (next = node.next) delete node.next;
  if (previous) return next ? previous.next = next : delete previous.next, this;
  if (!parent) return this._root = next, this;
  next ? parent[i] = next : delete parent[i];
  if ((node = parent[0] || parent[1] || parent[2] || parent[3] || parent[4] || parent[5] || parent[6] || parent[7]) && node === (parent[7] || parent[6] || parent[5] || parent[4] || parent[3] || parent[2] || parent[1] || parent[0]) && !node.length) {
    if (retainer) retainer[j] = node;
    else this._root = node;
  }
  return this;
}
function removeAll2(data) {
  for (var i = 0, n = data.length; i < n; ++i) this.remove(data[i]);
  return this;
}

// node_modules/d3-octree/src/root.js
function root_default2() {
  return this._root;
}

// node_modules/d3-octree/src/size.js
function size_default2() {
  var size = 0;
  this.visit(function(node) {
    if (!node.length) do
      ++size;
    while (node = node.next);
  });
  return size;
}

// node_modules/d3-octree/src/visit.js
function visit_default2(callback) {
  var octs = [], q, node = this._root, child, x0, y0, z0, x1, y1, z1;
  if (node) octs.push(new octant_default(node, this._x0, this._y0, this._z0, this._x1, this._y1, this._z1));
  while (q = octs.pop()) {
    if (!callback(node = q.node, x0 = q.x0, y0 = q.y0, z0 = q.z0, x1 = q.x1, y1 = q.y1, z1 = q.z1) && node.length) {
      var xm = (x0 + x1) / 2, ym = (y0 + y1) / 2, zm = (z0 + z1) / 2;
      if (child = node[7]) octs.push(new octant_default(child, xm, ym, zm, x1, y1, z1));
      if (child = node[6]) octs.push(new octant_default(child, x0, ym, zm, xm, y1, z1));
      if (child = node[5]) octs.push(new octant_default(child, xm, y0, zm, x1, ym, z1));
      if (child = node[4]) octs.push(new octant_default(child, x0, y0, zm, xm, ym, z1));
      if (child = node[3]) octs.push(new octant_default(child, xm, ym, z0, x1, y1, zm));
      if (child = node[2]) octs.push(new octant_default(child, x0, ym, z0, xm, y1, zm));
      if (child = node[1]) octs.push(new octant_default(child, xm, y0, z0, x1, ym, zm));
      if (child = node[0]) octs.push(new octant_default(child, x0, y0, z0, xm, ym, zm));
    }
  }
  return this;
}

// node_modules/d3-octree/src/visitAfter.js
function visitAfter_default2(callback) {
  var octs = [], next = [], q;
  if (this._root) octs.push(new octant_default(this._root, this._x0, this._y0, this._z0, this._x1, this._y1, this._z1));
  while (q = octs.pop()) {
    var node = q.node;
    if (node.length) {
      var child, x0 = q.x0, y0 = q.y0, z0 = q.z0, x1 = q.x1, y1 = q.y1, z1 = q.z1, xm = (x0 + x1) / 2, ym = (y0 + y1) / 2, zm = (z0 + z1) / 2;
      if (child = node[0]) octs.push(new octant_default(child, x0, y0, z0, xm, ym, zm));
      if (child = node[1]) octs.push(new octant_default(child, xm, y0, z0, x1, ym, zm));
      if (child = node[2]) octs.push(new octant_default(child, x0, ym, z0, xm, y1, zm));
      if (child = node[3]) octs.push(new octant_default(child, xm, ym, z0, x1, y1, zm));
      if (child = node[4]) octs.push(new octant_default(child, x0, y0, zm, xm, ym, z1));
      if (child = node[5]) octs.push(new octant_default(child, xm, y0, zm, x1, ym, z1));
      if (child = node[6]) octs.push(new octant_default(child, x0, ym, zm, xm, y1, z1));
      if (child = node[7]) octs.push(new octant_default(child, xm, ym, zm, x1, y1, z1));
    }
    next.push(q);
  }
  while (q = next.pop()) {
    callback(q.node, q.x0, q.y0, q.z0, q.x1, q.y1, q.z1);
  }
  return this;
}

// node_modules/d3-octree/src/x.js
function defaultX2(d) {
  return d[0];
}
function x_default2(_) {
  return arguments.length ? (this._x = _, this) : this._x;
}

// node_modules/d3-octree/src/y.js
function defaultY(d) {
  return d[1];
}
function y_default(_) {
  return arguments.length ? (this._y = _, this) : this._y;
}

// node_modules/d3-octree/src/z.js
function defaultZ(d) {
  return d[2];
}
function z_default(_) {
  return arguments.length ? (this._z = _, this) : this._z;
}

// node_modules/d3-octree/src/octree.js
function octree(nodes, x3, y3, z3) {
  var tree = new Octree(x3 == null ? defaultX2 : x3, y3 == null ? defaultY : y3, z3 == null ? defaultZ : z3, NaN, NaN, NaN, NaN, NaN, NaN);
  return nodes == null ? tree : tree.addAll(nodes);
}
function Octree(x3, y3, z3, x0, y0, z0, x1, y1, z1) {
  this._x = x3;
  this._y = y3;
  this._z = z3;
  this._x0 = x0;
  this._y0 = y0;
  this._z0 = z0;
  this._x1 = x1;
  this._y1 = y1;
  this._z1 = z1;
  this._root = void 0;
}
function leaf_copy2(leaf) {
  var copy = { data: leaf.data }, next = copy;
  while (leaf = leaf.next) next = next.next = { data: leaf.data };
  return copy;
}
var treeProto2 = octree.prototype = Octree.prototype;
treeProto2.copy = function() {
  var copy = new Octree(this._x, this._y, this._z, this._x0, this._y0, this._z0, this._x1, this._y1, this._z1), node = this._root, nodes, child;
  if (!node) return copy;
  if (!node.length) return copy._root = leaf_copy2(node), copy;
  nodes = [{ source: node, target: copy._root = new Array(8) }];
  while (node = nodes.pop()) {
    for (var i = 0; i < 8; ++i) {
      if (child = node.source[i]) {
        if (child.length) nodes.push({ source: child, target: node.target[i] = new Array(8) });
        else node.target[i] = leaf_copy2(child);
      }
    }
  }
  return copy;
};
treeProto2.add = add_default2;
treeProto2.addAll = addAll2;
treeProto2.cover = cover_default2;
treeProto2.data = data_default2;
treeProto2.extent = extent_default2;
treeProto2.find = find_default2;
treeProto2.findAllWithinRadius = findAllWithinRadius;
treeProto2.remove = remove_default2;
treeProto2.removeAll = removeAll2;
treeProto2.root = root_default2;
treeProto2.size = size_default2;
treeProto2.visit = visit_default2;
treeProto2.visitAfter = visitAfter_default2;
treeProto2.x = x_default2;
treeProto2.y = y_default;
treeProto2.z = z_default;

// node_modules/d3-force-3d/src/constant.js
function constant_default(x3) {
  return function() {
    return x3;
  };
}

// node_modules/d3-force-3d/src/jiggle.js
function jiggle_default(random) {
  return (random() - 0.5) * 1e-6;
}

// node_modules/d3-force-3d/src/collide.js
function x(d) {
  return d.x + d.vx;
}
function y(d) {
  return d.y + d.vy;
}
function z(d) {
  return d.z + d.vz;
}
function collide_default(radius) {
  var nodes, nDim, radii, random, strength = 1, iterations = 1;
  if (typeof radius !== "function") radius = constant_default(radius == null ? 1 : +radius);
  function force() {
    var i, n = nodes.length, tree, node, xi, yi, zi, ri, ri2;
    for (var k = 0; k < iterations; ++k) {
      tree = (nDim === 1 ? binarytree(nodes, x) : nDim === 2 ? quadtree(nodes, x, y) : nDim === 3 ? octree(nodes, x, y, z) : null).visitAfter(prepare);
      for (i = 0; i < n; ++i) {
        node = nodes[i];
        ri = radii[node.index], ri2 = ri * ri;
        xi = node.x + node.vx;
        if (nDim > 1) {
          yi = node.y + node.vy;
        }
        if (nDim > 2) {
          zi = node.z + node.vz;
        }
        tree.visit(apply);
      }
    }
    function apply(treeNode, arg1, arg2, arg3, arg4, arg5, arg6) {
      var args = [arg1, arg2, arg3, arg4, arg5, arg6];
      var x0 = args[0], y0 = args[1], z0 = args[2], x1 = args[nDim], y1 = args[nDim + 1], z1 = args[nDim + 2];
      var data = treeNode.data, rj = treeNode.r, r = ri + rj;
      if (data) {
        if (data.index > node.index) {
          var x3 = xi - data.x - data.vx, y3 = nDim > 1 ? yi - data.y - data.vy : 0, z3 = nDim > 2 ? zi - data.z - data.vz : 0, l = x3 * x3 + y3 * y3 + z3 * z3;
          if (l < r * r) {
            if (x3 === 0) x3 = jiggle_default(random), l += x3 * x3;
            if (nDim > 1 && y3 === 0) y3 = jiggle_default(random), l += y3 * y3;
            if (nDim > 2 && z3 === 0) z3 = jiggle_default(random), l += z3 * z3;
            l = (r - (l = Math.sqrt(l))) / l * strength;
            node.vx += (x3 *= l) * (r = (rj *= rj) / (ri2 + rj));
            if (nDim > 1) {
              node.vy += (y3 *= l) * r;
            }
            if (nDim > 2) {
              node.vz += (z3 *= l) * r;
            }
            data.vx -= x3 * (r = 1 - r);
            if (nDim > 1) {
              data.vy -= y3 * r;
            }
            if (nDim > 2) {
              data.vz -= z3 * r;
            }
          }
        }
        return;
      }
      return x0 > xi + r || x1 < xi - r || nDim > 1 && (y0 > yi + r || y1 < yi - r) || nDim > 2 && (z0 > zi + r || z1 < zi - r);
    }
  }
  function prepare(treeNode) {
    if (treeNode.data) return treeNode.r = radii[treeNode.data.index];
    for (var i = treeNode.r = 0; i < Math.pow(2, nDim); ++i) {
      if (treeNode[i] && treeNode[i].r > treeNode.r) {
        treeNode.r = treeNode[i].r;
      }
    }
  }
  function initialize() {
    if (!nodes) return;
    var i, n = nodes.length, node;
    radii = new Array(n);
    for (i = 0; i < n; ++i) node = nodes[i], radii[node.index] = +radius(node, i, nodes);
  }
  force.initialize = function(_nodes, ...args) {
    nodes = _nodes;
    random = args.find((arg) => typeof arg === "function") || Math.random;
    nDim = args.find((arg) => [1, 2, 3].includes(arg)) || 2;
    initialize();
  };
  force.iterations = function(_) {
    return arguments.length ? (iterations = +_, force) : iterations;
  };
  force.strength = function(_) {
    return arguments.length ? (strength = +_, force) : strength;
  };
  force.radius = function(_) {
    return arguments.length ? (radius = typeof _ === "function" ? _ : constant_default(+_), initialize(), force) : radius;
  };
  return force;
}

// node_modules/d3-force-3d/src/link.js
function index(d) {
  return d.index;
}
function find(nodeById, nodeId) {
  var node = nodeById.get(nodeId);
  if (!node) throw new Error("node not found: " + nodeId);
  return node;
}
function link_default(links) {
  var id = index, strength = defaultStrength, strengths, distance2 = constant_default(30), distances, nodes, nDim, count, bias, random, iterations = 1;
  if (links == null) links = [];
  function defaultStrength(link) {
    return 1 / Math.min(count[link.source.index], count[link.target.index]);
  }
  function force(alpha) {
    for (var k = 0, n = links.length; k < iterations; ++k) {
      for (var i = 0, link, source, target, x3 = 0, y3 = 0, z3 = 0, l, b; i < n; ++i) {
        link = links[i], source = link.source, target = link.target;
        x3 = target.x + target.vx - source.x - source.vx || jiggle_default(random);
        if (nDim > 1) {
          y3 = target.y + target.vy - source.y - source.vy || jiggle_default(random);
        }
        if (nDim > 2) {
          z3 = target.z + target.vz - source.z - source.vz || jiggle_default(random);
        }
        l = Math.sqrt(x3 * x3 + y3 * y3 + z3 * z3);
        l = (l - distances[i]) / l * alpha * strengths[i];
        x3 *= l, y3 *= l, z3 *= l;
        target.vx -= x3 * (b = bias[i]);
        if (nDim > 1) {
          target.vy -= y3 * b;
        }
        if (nDim > 2) {
          target.vz -= z3 * b;
        }
        source.vx += x3 * (b = 1 - b);
        if (nDim > 1) {
          source.vy += y3 * b;
        }
        if (nDim > 2) {
          source.vz += z3 * b;
        }
      }
    }
  }
  function initialize() {
    if (!nodes) return;
    var i, n = nodes.length, m2 = links.length, nodeById = new Map(nodes.map((d, i2) => [id(d, i2, nodes), d])), link;
    for (i = 0, count = new Array(n); i < m2; ++i) {
      link = links[i], link.index = i;
      if (typeof link.source !== "object") link.source = find(nodeById, link.source);
      if (typeof link.target !== "object") link.target = find(nodeById, link.target);
      count[link.source.index] = (count[link.source.index] || 0) + 1;
      count[link.target.index] = (count[link.target.index] || 0) + 1;
    }
    for (i = 0, bias = new Array(m2); i < m2; ++i) {
      link = links[i], bias[i] = count[link.source.index] / (count[link.source.index] + count[link.target.index]);
    }
    strengths = new Array(m2), initializeStrength();
    distances = new Array(m2), initializeDistance();
  }
  function initializeStrength() {
    if (!nodes) return;
    for (var i = 0, n = links.length; i < n; ++i) {
      strengths[i] = +strength(links[i], i, links);
    }
  }
  function initializeDistance() {
    if (!nodes) return;
    for (var i = 0, n = links.length; i < n; ++i) {
      distances[i] = +distance2(links[i], i, links);
    }
  }
  force.initialize = function(_nodes, ...args) {
    nodes = _nodes;
    random = args.find((arg) => typeof arg === "function") || Math.random;
    nDim = args.find((arg) => [1, 2, 3].includes(arg)) || 2;
    initialize();
  };
  force.links = function(_) {
    return arguments.length ? (links = _, initialize(), force) : links;
  };
  force.id = function(_) {
    return arguments.length ? (id = _, force) : id;
  };
  force.iterations = function(_) {
    return arguments.length ? (iterations = +_, force) : iterations;
  };
  force.strength = function(_) {
    return arguments.length ? (strength = typeof _ === "function" ? _ : constant_default(+_), initializeStrength(), force) : strength;
  };
  force.distance = function(_) {
    return arguments.length ? (distance2 = typeof _ === "function" ? _ : constant_default(+_), initializeDistance(), force) : distance2;
  };
  return force;
}

// node_modules/d3-force-3d/src/manyBody.js
import { quadtree as quadtree2 } from "d3-quadtree";

// node_modules/d3-force-3d/src/simulation.js
import { dispatch } from "d3-dispatch";
import { timer } from "d3-timer";

// node_modules/d3-force-3d/src/lcg.js
var a = 1664525;
var c = 1013904223;
var m = 4294967296;
function lcg_default() {
  let s = 1;
  return () => (s = (a * s + c) % m) / m;
}

// node_modules/d3-force-3d/src/simulation.js
var MAX_DIMENSIONS = 3;
function x2(d) {
  return d.x;
}
function y2(d) {
  return d.y;
}
function z2(d) {
  return d.z;
}
var initialRadius = 10;
var initialAngleRoll = Math.PI * (3 - Math.sqrt(5));
var initialAngleYaw = Math.PI * 20 / (9 + Math.sqrt(221));
function simulation_default(nodes, numDimensions) {
  numDimensions = numDimensions || 2;
  var nDim = Math.min(MAX_DIMENSIONS, Math.max(1, Math.round(numDimensions))), simulation, alpha = 1, alphaMin = 1e-3, alphaDecay = 1 - Math.pow(alphaMin, 1 / 300), alphaTarget = 0, velocityDecay = 0.6, forces = /* @__PURE__ */ new Map(), stepper = timer(step), event = dispatch("tick", "end"), random = lcg_default();
  if (nodes == null) nodes = [];
  function step() {
    tick();
    event.call("tick", simulation);
    if (alpha < alphaMin) {
      stepper.stop();
      event.call("end", simulation);
    }
  }
  function tick(iterations) {
    var i, n = nodes.length, node;
    if (iterations === void 0) iterations = 1;
    for (var k = 0; k < iterations; ++k) {
      alpha += (alphaTarget - alpha) * alphaDecay;
      forces.forEach(function(force) {
        force(alpha);
      });
      for (i = 0; i < n; ++i) {
        node = nodes[i];
        if (node.fx == null) node.x += node.vx *= velocityDecay;
        else node.x = node.fx, node.vx = 0;
        if (nDim > 1) {
          if (node.fy == null) node.y += node.vy *= velocityDecay;
          else node.y = node.fy, node.vy = 0;
        }
        if (nDim > 2) {
          if (node.fz == null) node.z += node.vz *= velocityDecay;
          else node.z = node.fz, node.vz = 0;
        }
      }
    }
    return simulation;
  }
  function initializeNodes() {
    for (var i = 0, n = nodes.length, node; i < n; ++i) {
      node = nodes[i], node.index = i;
      if (node.fx != null) node.x = node.fx;
      if (node.fy != null) node.y = node.fy;
      if (node.fz != null) node.z = node.fz;
      if (isNaN(node.x) || nDim > 1 && isNaN(node.y) || nDim > 2 && isNaN(node.z)) {
        var radius = initialRadius * (nDim > 2 ? Math.cbrt(0.5 + i) : nDim > 1 ? Math.sqrt(0.5 + i) : i), rollAngle = i * initialAngleRoll, yawAngle = i * initialAngleYaw;
        if (nDim === 1) {
          node.x = radius;
        } else if (nDim === 2) {
          node.x = radius * Math.cos(rollAngle);
          node.y = radius * Math.sin(rollAngle);
        } else {
          node.x = radius * Math.sin(rollAngle) * Math.cos(yawAngle);
          node.y = radius * Math.cos(rollAngle);
          node.z = radius * Math.sin(rollAngle) * Math.sin(yawAngle);
        }
      }
      if (isNaN(node.vx) || nDim > 1 && isNaN(node.vy) || nDim > 2 && isNaN(node.vz)) {
        node.vx = 0;
        if (nDim > 1) {
          node.vy = 0;
        }
        if (nDim > 2) {
          node.vz = 0;
        }
      }
    }
  }
  function initializeForce(force) {
    if (force.initialize) force.initialize(nodes, random, nDim);
    return force;
  }
  initializeNodes();
  return simulation = {
    tick,
    restart: function() {
      return stepper.restart(step), simulation;
    },
    stop: function() {
      return stepper.stop(), simulation;
    },
    numDimensions: function(_) {
      return arguments.length ? (nDim = Math.min(MAX_DIMENSIONS, Math.max(1, Math.round(_))), forces.forEach(initializeForce), simulation) : nDim;
    },
    nodes: function(_) {
      return arguments.length ? (nodes = _, initializeNodes(), forces.forEach(initializeForce), simulation) : nodes;
    },
    alpha: function(_) {
      return arguments.length ? (alpha = +_, simulation) : alpha;
    },
    alphaMin: function(_) {
      return arguments.length ? (alphaMin = +_, simulation) : alphaMin;
    },
    alphaDecay: function(_) {
      return arguments.length ? (alphaDecay = +_, simulation) : +alphaDecay;
    },
    alphaTarget: function(_) {
      return arguments.length ? (alphaTarget = +_, simulation) : alphaTarget;
    },
    velocityDecay: function(_) {
      return arguments.length ? (velocityDecay = 1 - _, simulation) : 1 - velocityDecay;
    },
    randomSource: function(_) {
      return arguments.length ? (random = _, forces.forEach(initializeForce), simulation) : random;
    },
    force: function(name, _) {
      return arguments.length > 1 ? (_ == null ? forces.delete(name) : forces.set(name, initializeForce(_)), simulation) : forces.get(name);
    },
    find: function() {
      var args = Array.prototype.slice.call(arguments);
      var x3 = args.shift() || 0, y3 = (nDim > 1 ? args.shift() : null) || 0, z3 = (nDim > 2 ? args.shift() : null) || 0, radius = args.shift() || Infinity;
      var i = 0, n = nodes.length, dx, dy, dz, d2, node, closest;
      radius *= radius;
      for (i = 0; i < n; ++i) {
        node = nodes[i];
        dx = x3 - node.x;
        dy = y3 - (node.y || 0);
        dz = z3 - (node.z || 0);
        d2 = dx * dx + dy * dy + dz * dz;
        if (d2 < radius) closest = node, radius = d2;
      }
      return closest;
    },
    on: function(name, _) {
      return arguments.length > 1 ? (event.on(name, _), simulation) : event.on(name);
    }
  };
}

// node_modules/d3-force-3d/src/manyBody.js
function manyBody_default() {
  var nodes, nDim, node, random, alpha, strength = constant_default(-30), strengths, distanceMin2 = 1, distanceMax2 = Infinity, theta2 = 0.81;
  function force(_) {
    var i, n = nodes.length, tree = (nDim === 1 ? binarytree(nodes, x2) : nDim === 2 ? quadtree2(nodes, x2, y2) : nDim === 3 ? octree(nodes, x2, y2, z2) : null).visitAfter(accumulate);
    for (alpha = _, i = 0; i < n; ++i) node = nodes[i], tree.visit(apply);
  }
  function initialize() {
    if (!nodes) return;
    var i, n = nodes.length, node2;
    strengths = new Array(n);
    for (i = 0; i < n; ++i) node2 = nodes[i], strengths[node2.index] = +strength(node2, i, nodes);
  }
  function accumulate(treeNode) {
    var strength2 = 0, q, c2, weight = 0, x3, y3, z3, i;
    var numChildren = treeNode.length;
    if (numChildren) {
      for (x3 = y3 = z3 = i = 0; i < numChildren; ++i) {
        if ((q = treeNode[i]) && (c2 = Math.abs(q.value))) {
          strength2 += q.value, weight += c2, x3 += c2 * (q.x || 0), y3 += c2 * (q.y || 0), z3 += c2 * (q.z || 0);
        }
      }
      strength2 *= Math.sqrt(4 / numChildren);
      treeNode.x = x3 / weight;
      if (nDim > 1) {
        treeNode.y = y3 / weight;
      }
      if (nDim > 2) {
        treeNode.z = z3 / weight;
      }
    } else {
      q = treeNode;
      q.x = q.data.x;
      if (nDim > 1) {
        q.y = q.data.y;
      }
      if (nDim > 2) {
        q.z = q.data.z;
      }
      do
        strength2 += strengths[q.data.index];
      while (q = q.next);
    }
    treeNode.value = strength2;
  }
  function apply(treeNode, x1, arg1, arg2, arg3) {
    if (!treeNode.value) return true;
    var x22 = [arg1, arg2, arg3][nDim - 1];
    var x3 = treeNode.x - node.x, y3 = nDim > 1 ? treeNode.y - node.y : 0, z3 = nDim > 2 ? treeNode.z - node.z : 0, w = x22 - x1, l = x3 * x3 + y3 * y3 + z3 * z3;
    if (w * w / theta2 < l) {
      if (l < distanceMax2) {
        if (x3 === 0) x3 = jiggle_default(random), l += x3 * x3;
        if (nDim > 1 && y3 === 0) y3 = jiggle_default(random), l += y3 * y3;
        if (nDim > 2 && z3 === 0) z3 = jiggle_default(random), l += z3 * z3;
        if (l < distanceMin2) l = Math.sqrt(distanceMin2 * l);
        node.vx += x3 * treeNode.value * alpha / l;
        if (nDim > 1) {
          node.vy += y3 * treeNode.value * alpha / l;
        }
        if (nDim > 2) {
          node.vz += z3 * treeNode.value * alpha / l;
        }
      }
      return true;
    } else if (treeNode.length || l >= distanceMax2) return;
    if (treeNode.data !== node || treeNode.next) {
      if (x3 === 0) x3 = jiggle_default(random), l += x3 * x3;
      if (nDim > 1 && y3 === 0) y3 = jiggle_default(random), l += y3 * y3;
      if (nDim > 2 && z3 === 0) z3 = jiggle_default(random), l += z3 * z3;
      if (l < distanceMin2) l = Math.sqrt(distanceMin2 * l);
    }
    do
      if (treeNode.data !== node) {
        w = strengths[treeNode.data.index] * alpha / l;
        node.vx += x3 * w;
        if (nDim > 1) {
          node.vy += y3 * w;
        }
        if (nDim > 2) {
          node.vz += z3 * w;
        }
      }
    while (treeNode = treeNode.next);
  }
  force.initialize = function(_nodes, ...args) {
    nodes = _nodes;
    random = args.find((arg) => typeof arg === "function") || Math.random;
    nDim = args.find((arg) => [1, 2, 3].includes(arg)) || 2;
    initialize();
  };
  force.strength = function(_) {
    return arguments.length ? (strength = typeof _ === "function" ? _ : constant_default(+_), initialize(), force) : strength;
  };
  force.distanceMin = function(_) {
    return arguments.length ? (distanceMin2 = _ * _, force) : Math.sqrt(distanceMin2);
  };
  force.distanceMax = function(_) {
    return arguments.length ? (distanceMax2 = _ * _, force) : Math.sqrt(distanceMax2);
  };
  force.theta = function(_) {
    return arguments.length ? (theta2 = _ * _, force) : Math.sqrt(theta2);
  };
  return force;
}

// node_modules/d3-force-3d/src/radial.js
function radial_default(radius, x3, y3, z3) {
  var nodes, nDim, strength = constant_default(0.1), strengths, radiuses;
  if (typeof radius !== "function") radius = constant_default(+radius);
  if (x3 == null) x3 = 0;
  if (y3 == null) y3 = 0;
  if (z3 == null) z3 = 0;
  function force(alpha) {
    for (var i = 0, n = nodes.length; i < n; ++i) {
      var node = nodes[i], dx = node.x - x3 || 1e-6, dy = (node.y || 0) - y3 || 1e-6, dz = (node.z || 0) - z3 || 1e-6, r = Math.sqrt(dx * dx + dy * dy + dz * dz), k = (radiuses[i] - r) * strengths[i] * alpha / r;
      node.vx += dx * k;
      if (nDim > 1) {
        node.vy += dy * k;
      }
      if (nDim > 2) {
        node.vz += dz * k;
      }
    }
  }
  function initialize() {
    if (!nodes) return;
    var i, n = nodes.length;
    strengths = new Array(n);
    radiuses = new Array(n);
    for (i = 0; i < n; ++i) {
      radiuses[i] = +radius(nodes[i], i, nodes);
      strengths[i] = isNaN(radiuses[i]) ? 0 : +strength(nodes[i], i, nodes);
    }
  }
  force.initialize = function(initNodes, ...args) {
    nodes = initNodes;
    nDim = args.find((arg) => [1, 2, 3].includes(arg)) || 2;
    initialize();
  };
  force.strength = function(_) {
    return arguments.length ? (strength = typeof _ === "function" ? _ : constant_default(+_), initialize(), force) : strength;
  };
  force.radius = function(_) {
    return arguments.length ? (radius = typeof _ === "function" ? _ : constant_default(+_), initialize(), force) : radius;
  };
  force.x = function(_) {
    return arguments.length ? (x3 = +_, force) : x3;
  };
  force.y = function(_) {
    return arguments.length ? (y3 = +_, force) : y3;
  };
  force.z = function(_) {
    return arguments.length ? (z3 = +_, force) : z3;
  };
  return force;
}

// node_modules/d3-force-3d/src/x.js
function x_default3(x3) {
  var strength = constant_default(0.1), nodes, strengths, xz;
  if (typeof x3 !== "function") x3 = constant_default(x3 == null ? 0 : +x3);
  function force(alpha) {
    for (var i = 0, n = nodes.length, node; i < n; ++i) {
      node = nodes[i], node.vx += (xz[i] - node.x) * strengths[i] * alpha;
    }
  }
  function initialize() {
    if (!nodes) return;
    var i, n = nodes.length;
    strengths = new Array(n);
    xz = new Array(n);
    for (i = 0; i < n; ++i) {
      strengths[i] = isNaN(xz[i] = +x3(nodes[i], i, nodes)) ? 0 : +strength(nodes[i], i, nodes);
    }
  }
  force.initialize = function(_) {
    nodes = _;
    initialize();
  };
  force.strength = function(_) {
    return arguments.length ? (strength = typeof _ === "function" ? _ : constant_default(+_), initialize(), force) : strength;
  };
  force.x = function(_) {
    return arguments.length ? (x3 = typeof _ === "function" ? _ : constant_default(+_), initialize(), force) : x3;
  };
  return force;
}

// node_modules/d3-force-3d/src/y.js
function y_default2(y3) {
  var strength = constant_default(0.1), nodes, strengths, yz;
  if (typeof y3 !== "function") y3 = constant_default(y3 == null ? 0 : +y3);
  function force(alpha) {
    for (var i = 0, n = nodes.length, node; i < n; ++i) {
      node = nodes[i], node.vy += (yz[i] - node.y) * strengths[i] * alpha;
    }
  }
  function initialize() {
    if (!nodes) return;
    var i, n = nodes.length;
    strengths = new Array(n);
    yz = new Array(n);
    for (i = 0; i < n; ++i) {
      strengths[i] = isNaN(yz[i] = +y3(nodes[i], i, nodes)) ? 0 : +strength(nodes[i], i, nodes);
    }
  }
  force.initialize = function(_) {
    nodes = _;
    initialize();
  };
  force.strength = function(_) {
    return arguments.length ? (strength = typeof _ === "function" ? _ : constant_default(+_), initialize(), force) : strength;
  };
  force.y = function(_) {
    return arguments.length ? (y3 = typeof _ === "function" ? _ : constant_default(+_), initialize(), force) : y3;
  };
  return force;
}

// node_modules/d3-force-3d/src/z.js
function z_default2(z3) {
  var strength = constant_default(0.1), nodes, strengths, zz;
  if (typeof z3 !== "function") z3 = constant_default(z3 == null ? 0 : +z3);
  function force(alpha) {
    for (var i = 0, n = nodes.length, node; i < n; ++i) {
      node = nodes[i], node.vz += (zz[i] - node.z) * strengths[i] * alpha;
    }
  }
  function initialize() {
    if (!nodes) return;
    var i, n = nodes.length;
    strengths = new Array(n);
    zz = new Array(n);
    for (i = 0; i < n; ++i) {
      strengths[i] = isNaN(zz[i] = +z3(nodes[i], i, nodes)) ? 0 : +strength(nodes[i], i, nodes);
    }
  }
  force.initialize = function(_) {
    nodes = _;
    initialize();
  };
  force.strength = function(_) {
    return arguments.length ? (strength = typeof _ === "function" ? _ : constant_default(+_), initialize(), force) : strength;
  };
  force.z = function(_) {
    return arguments.length ? (z3 = typeof _ === "function" ? _ : constant_default(+_), initialize(), force) : z3;
  };
  return force;
}
export {
  center_default as forceCenter,
  collide_default as forceCollide,
  link_default as forceLink,
  manyBody_default as forceManyBody,
  radial_default as forceRadial,
  simulation_default as forceSimulation,
  x_default3 as forceX,
  y_default2 as forceY,
  z_default2 as forceZ
};
