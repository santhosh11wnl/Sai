# -*- coding: utf-8 -*-
from __future__ import print_function
from google.cloud import vision_v1 as vision
# from google.cloud.vision.vision import types
import io,os, json
os.environ['GOOGLE_APPLICATION_CREDENTIALS']=r'D:/pathway/pathway_backend/backend/pathway_module/Pathway-3f29d8393d4b.json'
import numpy as np


# image_uri = 'gs://cloud-vision-codelab/otter_crossing.jpg'
def gcv_ocr(file_name):

    # path = '/home/fei/Desktop/weiwei/pathway_web/SkyEye/users/upload-files/test_img/cin_00085.jpg'
    with io.open(file_name, 'rb') as image_file:
        content = image_file.read()

    client = vision.ImageAnnotatorClient()
    # image = vision.types.Image()
    # image.source.image_uri = image_uri
    image = vision.types.Image(content=content)
    #response = client.text_detection(image=image, image_context = {"language_hints" : ["en"]})
    
    
    with open('./pathway_module/OCR_Response.json', 'r') as file:
      # Read the contents of the file
        json_data = file.read()

      # Parse the JSON data
        response = json.loads(json_data)
    results=[]
    coordinates_list=[]
    print("response data Bypassed By Basheer")
    for text in response["text_annotations"]:
        # print('=' * 30)
        result = text["description"]
        # result=text.description.encode("gbk").decode('gbk')
        vertices = [[v['x'], v['y']] for v in text["boundingPoly"]["vertices"]]
        # print('bounds:', ",".join(vertices))
        results.append(result)
        coordinates_list.append(vertices)
    return results, coordinates_list



if __name__ == "__main__":
    gcv_ocr('/home/fei/Desktop/weiwei/pathway_web/SkyEye/users/upload-files/test_img/cin_00085.jpg')