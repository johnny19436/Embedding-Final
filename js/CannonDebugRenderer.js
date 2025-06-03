/**
 * @author schteppe / https://github.com/schteppe
 * @author Grégory Coiffier / https://github.com/greglabs
 */
var CannonDebugRenderer = function(scene, world, options){
    options = options || {};

    this.scene = scene;
    this.world = world;

    this._meshes = [];

    this._material = new THREE.MeshBasicMaterial({ color: 0x00ff00, wireframe: true });
    this._sphereMaterial = new THREE.MeshBasicMaterial({ color: 0x0000ff, wireframe: true }); // Different color for spheres
    this._particleMaterial = new THREE.MeshBasicMaterial({ color: 0xff0000, wireframe: true }); // Different color for particles
    this._boxMaterial = new THREE.MeshBasicMaterial({ color: 0xff00ff, wireframe: true }); // Different color for boxes
    this._cylinderMaterial = new THREE.MeshBasicMaterial({ color: 0xffff00, wireframe: true }); // Yellow for cylinders, like your bat
    this._planeMaterial = new THREE.MeshBasicMaterial({ color: 0xcccccc, wireframe: true }); // Grey for planes

    this._vectorMaterial = new THREE.LineBasicMaterial({ color: 0xff0000 }); // For contact normals, etc.


    this._tmpVec0 = new CANNON.Vec3();
    this._tmpVec1 = new CANNON.Vec3();
    this._tmpVec2 = new CANNON.Vec3();
    this._tmpQuat0 = new CANNON.Quaternion();

    this.tmpLine = new THREE.BufferGeometry(); // For drawing lines like contact normals

    this.options = options;
    this.drawCANNONContacts = !!options.drawCANNONContacts; //New option to draw cannon contacts
};

CannonDebugRenderer.prototype = {

    constructor: CannonDebugRenderer,

    update: function(){

        var bodies = this.world.bodies;
        var N = bodies.length;

        // Clean up old meshes
        for(var i = 0; i < this._meshes.length; i++){
            this.scene.remove(this._meshes[i]);
        }
        this._meshes.length = 0;

        // Create new meshes for each body
        for(var i = 0; i < N; i++){
            var body = bodies[i];
            if(body.shapes.length){ // Only process bodies with shapes
                for (var j = 0; j < body.shapes.length; j++) {
                    var shape = body.shapes[j];
                    var mesh;
                    var material = this._material; // Default material

                    // Determine material based on shape type
                    if(shape instanceof CANNON.Sphere){
                        material = this._sphereMaterial;
                    } else if (shape instanceof CANNON.Particle) {
                        material = this._particleMaterial;
                    } else if (shape instanceof CANNON.Box) {
                        material = this._boxMaterial;
                    } else if (shape instanceof CANNON.Cylinder) {
                        material = this._cylinderMaterial;
                    } else if (shape instanceof CANNON.Plane) {
                        material = this._planeMaterial;
                    }


                    mesh = this._createMesh(shape, material); // Pass material to mesh creation

                    if(mesh){ // If mesh was created successfully
                        // Get world position
                        body.quaternion.vmult(body.shapeOffsets[j], this._tmpVec0);
                        body.position.vadd(this._tmpVec0, this._tmpVec0);
                        mesh.position.copy(this._tmpVec0);

                        // Get world quaternion
                        body.quaternion.mult(body.shapeOrientations[j], this._tmpQuat0);
                        mesh.quaternion.copy(this._tmpQuat0);

                        this.scene.add(mesh);
                        this._meshes.push(mesh);
                    }
                }
            }
        }
         // --- Draw CANNON Contacts (optional) ---
        if (this.drawCANNONContacts) {
            this.scene.remove(this.contactLines); // Remove old lines first

            var geometry = new THREE.BufferGeometry();
            var points = [];

            for (var i = 0; i < this.world.contacts.length; i++) {
                var c = this.world.contacts[i];
                // Contact point in world space
                var p1 = new THREE.Vector3(c.bi.position.x + c.ri.x, c.bi.position.y + c.ri.y, c.bi.position.z + c.ri.z);
                var p2 = new THREE.Vector3(c.bj.position.x + c.rj.x, c.bj.position.y + c.rj.y, c.bj.position.z + c.rj.z);
                
                points.push(p1.x, p1.y, p1.z);
                points.push(p2.x, p2.y, p2.z);

                // You could also draw the contact normal here
                // var normal = new THREE.Vector3(c.ni.x, c.ni.y, c.ni.z);
                // var endNormal = p1.clone().add(normal.multiplyScalar(0.2)); // Scale normal for visibility
                // points.push(p1.x, p1.y, p1.z);
                // points.push(endNormal.x, endNormal.y, endNormal.z);
            }
            
            if (points.length > 0) {
                geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
                this.contactLines = new THREE.LineSegments(geometry, this._vectorMaterial);
                this.scene.add(this.contactLines);
            }
        }

    },

    _createMesh: function(shape, material){ // Added material parameter
        var mesh;
        var MESH_SEGMENTS = 12; // Number of segments for curved shapes

        switch(shape.type){

        case CANNON.Shape.types.SPHERE:
            var sphere_geometry = new THREE.SphereGeometry( shape.radius, MESH_SEGMENTS, MESH_SEGMENTS );
            mesh = new THREE.Mesh( sphere_geometry, material ); // Use passed material
            break;

        case CANNON.Shape.types.PARTICLE:
            // Particles are often too small to see as wireframes. You might use a small sphere or Point object.
            var particle_geo = new THREE.SphereGeometry(0.05, 4, 4); // Small sphere for particle
            mesh = new THREE.Mesh(particle_geo, material);
            break;

        case CANNON.Shape.types.PLANE:
            var geometry = new THREE.PlaneGeometry(10, 10, 10, 10); // Default plane size
            mesh = new THREE.Mesh( geometry, material ); // Use passed material
            var q = new CANNON.Quaternion();
            q.setFromAxisAngle(new CANNON.Vec3(1,0,0),-Math.PI/2); // Rotate plane to be horizontal
            mesh.quaternion.set(q.x, q.y, q.z, q.w);
            break;

        case CANNON.Shape.types.BOX:
            var box_geometry = new THREE.BoxGeometry( shape.halfExtents.x*2,
                                                        shape.halfExtents.y*2,
                                                        shape.halfExtents.z*2 );
            mesh = new THREE.Mesh( box_geometry, material ); // Use passed material
            break;

        case CANNON.Shape.types.CONVEXPOLYHEDRON:
            var geo = new THREE.BufferGeometry();

            // Add vertices
            var G_vertices = [];
            for (var i = 0; i < shape.vertices.length; i++) {
                var v = shape.vertices[i];
                G_vertices.push(v.x, v.y, v.z);
            }
            geo.setAttribute('position', new THREE.Float32BufferAttribute(G_vertices, 3));

            // Add faces (indices)
            var G_indices = [];
            for(var i=0; i<shape.faces.length; i++){
                var face = shape.faces[i];
                var a = face[0];
                for (var j = 1; j < face.length - 1; j++) {
                    var b = face[j];
                    var c = face[j + 1];
                    G_indices.push(a, b, c);
                }
            }
            geo.setIndex(G_indices);
            geo.computeBoundingSphere();
            geo.computeVertexNormals(); // Needed for some materials if not wireframe

            mesh = new THREE.Mesh( geo, material ); // Use passed material
            break;

        case CANNON.Shape.types.HEIGHTFIELD:
            var geometry = new THREE.BufferGeometry();
            var v = [];
            var s = shape.elementSize || 1; // Default element size
            for (var i = 0; i < shape.data.length - 1; i++) {
                for (var j = 0; j < shape.data[i].length - 1; j++) {
                    // Add two triangles per grid cell
                    v.push(i * s,     j * s,     shape.data[i][j]);
                    v.push((i + 1)*s, j * s,     shape.data[i+1][j]);
                    v.push(i * s,     (j + 1)*s, shape.data[i][j+1]);

                    v.push((i + 1)*s, j * s,     shape.data[i+1][j]);
                    v.push((i + 1)*s, (j + 1)*s, shape.data[i+1][j+1]);
                    v.push(i * s,     (j + 1)*s, shape.data[i][j+1]);
                }
            }
            geometry.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
            geometry.computeBoundingSphere();
            geometry.computeVertexNormals();
            mesh = new THREE.Mesh(geometry, material); // Use passed material
            break;

        case CANNON.Shape.types.TRIMESH:
            var geometry = new THREE.BufferGeometry();
            var v = [];
            for(var i=0; i < shape.indices.length / 3; i++){
                shape.getTriangleVertices(i, this._tmpVec0, this._tmpVec1, this._tmpVec2);
                v.push(this._tmpVec0.x, this._tmpVec0.y, this._tmpVec0.z);
                v.push(this._tmpVec1.x, this._tmpVec1.y, this._tmpVec1.z);
                v.push(this._tmpVec2.x, this._tmpVec2.y, this._tmpVec2.z);
            }
            geometry.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
            geometry.computeBoundingSphere();
            geometry.computeVertexNormals();
            mesh = new THREE.Mesh(geometry, material); // Use passed material
            break;
        
        case CANNON.Shape.types.CYLINDER: // CANNON.js cylinder has its height along Y
            var G_SEGMENTS = shape.numSegments || MESH_SEGMENTS; // Use numSegments from shape if available
            var cylinder_geometry = new THREE.CylinderGeometry(shape.radiusTop, shape.radiusBottom, shape.height, G_SEGMENTS);
            mesh = new THREE.Mesh(cylinder_geometry, material); // Use passed material
            // The cylinder in Three.js is also Y-up by default, so usually no extra rotation needed here
            // unless the CANNON.Cylinder has a different orientation from its body,
            // which is handled by body.shapeOrientations[j] in the update function.
            break;

        default:
            console.warn("CannonDebugRenderer: Unhandled shape type:", shape.type);
            break;
        }

        if(mesh){
            //body.quaternion.vmult(body.shapeOffsets[j], mesh.position); // Offset is handled in update()
            //body.position.vadd(mesh.position, mesh.position);
            //body.quaternion.mult(body.shapeOrientations[j], mesh.quaternion); // Orientation is handled in update()
            //mesh.useQuaternion = true; // three.js r71
        }

        return mesh;
    }
};